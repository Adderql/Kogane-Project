"""
kogane.py — v6 (PyQt5 native)
Ctrl+Space      : show / hide
Ctrl+Shift+S    : screen snip → vision
Tray            : menu
"""

import sys, os, threading, subprocess, webbrowser, io, base64
import re, sqlite3, traceback, json, math, random
from urllib.parse import quote_plus

from dotenv import load_dotenv
load_dotenv()

from groq import Groq
import pystray
from PIL import Image as PILImage, ImageGrab
import keyboard

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QTextEdit, QFrame,
    QGraphicsOpacityEffect, QShortcut
)
from PyQt5.QtCore import (
    Qt, QObject, QTimer, QPropertyAnimation, QAbstractAnimation,
    QParallelAnimationGroup, QEasingCurve, QElapsedTimer, QPoint, QPointF,
    QRect, pyqtSignal, pyqtProperty, QThread
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QPixmap, QTextCursor,
    QPainterPath, QFontDatabase, QPalette, QKeySequence,
)

import kogane_animation
from kogane_animation import (
    KoganeIconWidget, ICON_SIZE, WIDGET_SIZE, _StarParticle,
)

# ── CONFIG ────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
HOTKEY       = "ctrl+space"
HOTKEY_SNIP  = "ctrl+shift+s"

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
ICON_PATH  = os.path.join(BASE_DIR, "kogane.png")
DB_PATH    = os.path.join(BASE_DIR, "kogane.db")
FONT_PATH  = os.path.join(BASE_DIR, "Inter.ttf")

PANEL_W, PANEL_H = 420, 650

SYSTEM_PROMPT = """You are Kogane — a personal AI bound to your user.
You're direct, sharp, and always on point. Keep answers short and clear.
When asked to open an app, reply ONLY: OPEN:appname.exe
When asked to search, reply ONLY: SEARCH:query
When asked about the screen or what's visible, reply ONLY: SCREEN
Otherwise respond in 1-3 sentences max."""

VISION_PROMPT = (
    "Describe what you see in this screenshot in 1-2 sentences, "
    "then ask what the user would like help with."
)

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
GROQ_TIMEOUT_S = 30  # a stalled connection must not lock the UI forever

# ── PALETTE ───────────────────────────────────────────────────────────
# Kogane (黄金) means gold. The accent is honey amber — personal, warm,
# nothing like the blue reflex of every other AI interface.
class P:
    bg             = "#17151E"   # panel background
    divider        = "#262330"   # header / input bar dividers

    surface        = "#232030"   # kogane bubbles, input field bg, typing bubble
    surface_border = "#322F40"   # input field resting border (gold only on focus)
    text           = "#EDEAF5"   # main text

    user_bubble = "#3A2E12"   # user bubble surface
    user_border = "#59461B"   # user bubble hairline border
    user_text   = "#F0C75E"   # user bubble text

    accent       = "#E8A825"  # gold accent — send button bg, focused input border
    accent_hover = "#F2B940"
    accent_press = "#C68F1E"
    accent_text  = "#2B1F04"  # dark glyph color on gold surfaces

    text_muted = "#8B87A0"    # placeholder / status / "online" label / captions
    muted_dim  = "#5C5870"    # disabled text

def _rgba(hex_color: str, alpha: int) -> str:
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"

print(f"[Kogane] P.surface_border = {P.surface_border}", flush=True)
print(f"[Kogane] P.accent = {P.accent}", flush=True)

# ── TYPOGRAPHY ────────────────────────────────────────────────────────
FONT_FAMILY = "Segoe UI"

def _load_font_family() -> str:
    if os.path.exists(FONT_PATH):
        font_id = QFontDatabase.addApplicationFont(FONT_PATH)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                print(f"[Kogane] Loaded font: {families[0]}", flush=True)
                return families[0]
        print("[Kogane] Inter.ttf found but failed to load — using Segoe UI", flush=True)
    else:
        print("[Kogane] Inter.ttf not found — using Segoe UI", flush=True)
    return "Segoe UI"

def _font_stack() -> str:
    return f"'{FONT_FAMILY}', 'Segoe UI', sans-serif"

# ── LaTeX → UNICODE ───────────────────────────────────────────────────
_SUP = {'0':'⁰','1':'¹','2':'²','3':'³','4':'⁴','5':'⁵','6':'⁶','7':'⁷',
        '8':'⁸','9':'⁹','+':'⁺','-':'⁻','n':'ⁿ','i':'ⁱ'}
_SUB = {'0':'₀','1':'₁','2':'₂','3':'₃','4':'₄','5':'₅','6':'₆','7':'₇',
        '8':'₈','9':'₉','+':'₊','-':'₋'}
_GREEK = {
    'alpha':'α','beta':'β','gamma':'γ','delta':'δ','epsilon':'ε','pi':'π',
    'theta':'θ','lambda':'λ','mu':'μ','sigma':'σ','omega':'ω','phi':'φ',
}
_OPS = [
    (r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1/\2)'),
    (r'\\sqrt\{([^{}]+)\}', r'√(\1)'),
    (r'\\pm\b','±'),(r'\\times\b','×'),(r'\\infty\b','∞'),
    (r'\\leq\b','≤'),(r'\\geq\b','≥'),(r'\\neq\b','≠'),
    (r'\\rightarrow\b','→'),(r'\\to\b','→'),
]

def clean_latex(text: str) -> str:
    text = re.sub(r'\$\$(.*?)\$\$', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'\$(.*?)\$', r'\1', text)
    for pat, rep in _OPS:
        text = re.sub(pat, rep, text)
    text = re.sub(r'\^\{([^{}]+)\}',
                  lambda m: ''.join(_SUP.get(c,c) for c in m.group(1)), text)
    text = re.sub(r'_\{([^{}]+)\}',
                  lambda m: ''.join(_SUB.get(c,c) for c in m.group(1)), text)
    for name, sym in _GREEK.items():
        text = re.sub(r'\\' + name + r'\b', sym, text)
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    text = re.sub(r'\{([^{}]*)\}', r'\1', text)
    return text.replace('{','').replace('}','')

# ── SQLITE HISTORY ────────────────────────────────────────────────────
_active_conv_id: int | None = None

def _db_init():
    with sqlite3.connect(DB_PATH) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS conversations (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER,
            role            TEXT,
            content         TEXT,
            timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id)
        )""")
        c.commit()

def _make_title(text: str) -> str:
    text = re.sub(r'^\[.*?\]\s*', '', text)
    text = re.sub(r'[A-Za-z0-9+/]{50,}={0,2}', '', text)
    return text.strip()[:40].rstrip() or "Conversation"

def db_new_conversation(title: str) -> int | None:
    try:
        with sqlite3.connect(DB_PATH) as c:
            cur = c.execute("INSERT INTO conversations (title) VALUES (?)", (title,))
            c.commit()
            return cur.lastrowid
    except Exception as exc:
        print(f"[Kogane] db_new_conversation failed: {exc}", flush=True)
        return None

def db_append(role: str, content: str):
    if _active_conv_id is None:
        return
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute(
                "INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
                (_active_conv_id, role, content)
            )
            c.execute(
                "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (_active_conv_id,)
            )
            c.commit()
    except Exception as exc:
        print(f"[Kogane] db_append failed: {exc}", flush=True)

def db_load_conversations(limit: int = 60) -> list:
    try:
        with sqlite3.connect(DB_PATH) as c:
            rows = c.execute(
                "SELECT id, title, updated_at FROM conversations "
                "ORDER BY updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"id": r[0], "title": r[1], "updated_at": r[2]} for r in rows]
    except Exception:
        return []

def db_load_messages(conv_id: int) -> list:
    try:
        with sqlite3.connect(DB_PATH) as c:
            rows = c.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id",
                (conv_id,)
            ).fetchall()
        return [{"role": r, "content": ct} for r, ct in rows]
    except Exception:
        return []

def db_delete_conversation(conv_id: int):
    try:
        with sqlite3.connect(DB_PATH) as c:
            c.execute("DELETE FROM messages WHERE conversation_id=?", (conv_id,))
            c.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
            c.commit()
    except Exception as exc:
        print(f"[Kogane] db_delete_conversation failed: {exc}", flush=True)

_db_init()

# ── AI CLIENTS ────────────────────────────────────────────────────────
groq_client: Groq = None
conversation_history: list = []

class _RateLimitError(Exception):
    pass

def _is_rate_limit(exc: Exception) -> bool:
    if getattr(exc, "status_code", None) == 429:
        return True
    m = str(exc).lower()
    return any(k in m for k in ("rate limit", "rate_limit", "429",
                                 "resource_exhausted", "too many requests"))

def _fmt_err(exc: Exception) -> str:
    msg = str(exc).replace("\n", " ").strip()
    return msg[:300] + ("…" if len(msg) > 300 else "")

def _user_facing_error(exc: Exception) -> str:
    if _is_rate_limit(exc):
        return "Too many requests — wait 30 s and try again."
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "Invalid API key. Check GROQ_API_KEY in your .env file."
    if status == 403:
        return "API access denied. Your key may lack permission for this model."
    if status in (502, 503, 504):
        return "Groq is temporarily unavailable. Try again in a moment."
    err = str(exc).lower()
    if any(k in err for k in ("connection", "timeout", "network", "resolve",
                               "unreachable", "eof", "ssl")):
        return "Can't reach Groq. Check your internet connection."
    return "Something went wrong. Try again."

def _debug_print_messages(label: str, msgs: list):
    # Redact base64 image payloads so the console stays readable, but keep
    # every message's role/shape intact so messages[0] is verifiably the
    # persona system prompt on every call.
    safe = []
    for m in msgs:
        content = m.get("content")
        if isinstance(content, list):
            safe_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    safe_content.append({"type": "image_url", "image_url": "<base64 omitted>"})
                else:
                    safe_content.append(part)
            safe.append({"role": m["role"], "content": safe_content})
        else:
            safe.append(m)
    print(f"[Kogane] Groq request ({label}) — {len(safe)} message(s): {safe}", flush=True)
    print(f"[Kogane] Groq request ({label}) — messages[0] = {safe[0]!r}", flush=True)

def _groq_vision(b64: str, prompt: str) -> str:
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": prompt}
        ]},
    ]
    _debug_print_messages("vision", msgs)
    r = groq_client.chat.completions.create(
        model=VISION_MODEL,
        messages=msgs,
        max_tokens=400,
        timeout=GROQ_TIMEOUT_S,
    )
    return clean_latex(r.choices[0].message.content.strip())

def ask_groq(user_input: str) -> str:
    conversation_history.append({"role": "user", "content": user_input})
    recent = conversation_history[-20:]
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + recent
    _debug_print_messages("chat", msgs)
    try:
        r = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile", messages=msgs, max_tokens=300,
            timeout=GROQ_TIMEOUT_S)
    except Exception as exc:
        if _is_rate_limit(exc):
            raise _RateLimitError() from exc
        raise
    reply = clean_latex(r.choices[0].message.content.strip())
    if not any(reply.startswith(p) for p in ("OPEN:", "SEARCH:", "SCREEN")):
        conversation_history.append({"role": "assistant", "content": reply})
        if len(conversation_history) > 40:
            del conversation_history[:2]
    return reply

def ask_groq_vision(b64: str, prompt: str = VISION_PROMPT) -> str:
    try:
        return _groq_vision(b64, prompt)
    except Exception as exc:
        if _is_rate_limit(exc):
            raise _RateLimitError() from exc
        raise

def ask_groq_with_image(user_input: str, b64: str) -> str:
    reply = _groq_vision(b64, user_input)
    conversation_history.append({"role": "user", "content": user_input})
    conversation_history.append({"role": "assistant", "content": reply})
    return reply

# ── SCREEN CAPTURE ────────────────────────────────────────────────────
def screen_to_b64(region=None) -> str:
    buf = io.BytesIO()
    ImageGrab.grab(bbox=region).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

# ── GROQ WORKER (QObject, moved to a QThread) ────────────────────────
# This object lives on a background QThread once started. Its run() method
# must NEVER touch a widget — it only calls the (pure, UI-free) network
# function and emits a signal with the resulting string. Qt automatically
# marshals that signal delivery onto the thread that owns the receiving
# slot (the main/GUI thread), so every widget update happens safely there.
class GroqWorker(QObject):
    response_ready = pyqtSignal(str)
    error          = pyqtSignal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception as exc:
            print(f"[Kogane] worker error: {_fmt_err(exc)}", flush=True)
            self.error.emit(_user_facing_error(exc))
            return
        self.response_ready.emit(result)


# ── REGION SELECTOR (screen snip overlay) ────────────────────────────
class RegionSelector(QWidget):
    region_selected = pyqtSignal(int, int, int, int)
    cancelled       = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self._start = self._end = None
        self._active = False
        self._dim_alpha = 0
        self._ant_off = 0.0
        self._ant_timer = QTimer(self)
        self._ant_timer.timeout.connect(self._tick)

    def getDimAlpha(self): return self._dim_alpha
    def setDimAlpha(self, v): self._dim_alpha = v; self.update()
    dimAlpha = pyqtProperty(int, getDimAlpha, setDimAlpha)

    def activate(self):
        vg = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(vg)
        self._start = self._end = None
        self._active = False
        self._dim_alpha = 0
        self.show(); self.raise_(); self.activateWindow(); self.setFocus()
        a = QPropertyAnimation(self, b"dimAlpha")
        a.setStartValue(0); a.setEndValue(110)
        a.setDuration(150); a.setEasingCurve(QEasingCurve.OutCubic)
        a.start(); self._anim = a

    def _tick(self):
        self._ant_off = (self._ant_off + 0.8) % 8.0
        if self._start and self._end:
            x1 = min(self._start.x(), self._end.x())
            y1 = min(self._start.y(), self._end.y())
            w  = abs(self._end.x()-self._start.x())
            h  = abs(self._end.y()-self._start.y())
            # Only repaint the selection border region
            self.update(QRect(x1-2, y1-2, w+4, h+4))
        else:
            self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._ant_timer.stop(); self.hide(); self.cancelled.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start = e.pos(); self._end = e.pos()
            self._active = True; self._ant_timer.start(25)

    def mouseMoveEvent(self, e):
        if self._active:
            self._end = e.pos(); self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._active:
            self._end = e.pos(); self._active = False
            self._ant_timer.stop(); self.hide()
            if self._start and self._end:
                x1 = min(self._start.x(), self._end.x())
                y1 = min(self._start.y(), self._end.y())
                x2 = max(self._start.x(), self._end.x())
                y2 = max(self._start.y(), self._end.y())
                if x2-x1 > 4 and y2-y1 > 4:
                    self.region_selected.emit(x1, y1, x2, y2)
                    return
            self.cancelled.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, self._dim_alpha))
        if self._start and self._end:
            x1 = min(self._start.x(), self._end.x())
            y1 = min(self._start.y(), self._end.y())
            w  = abs(self._end.x()-self._start.x())
            h  = abs(self._end.y()-self._start.y())
            sel = QRect(x1, y1, w, h)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(sel, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            for col, off in ((QColor(255,255,255,160), self._ant_off),
                             (QColor(200,144,28,210),  self._ant_off+4.0)):
                pen = QPen(col, 1.5, Qt.CustomDashLine)
                pen.setDashPattern([4.0,4.0]); pen.setDashOffset(off)
                p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRect(sel)
            p.setPen(QColor(255,255,255,180))
            p.setFont(QFont("Segoe UI Variable", 13))
            ly = y1-8 if y1>20 else y1+h+16
            p.drawText(x1+4, ly, f"{w} × {h}")
        else:
            p.setPen(QPen(QColor(255,255,255,80), 1))
            p.setFont(QFont("Segoe UI Variable", 13))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Click and drag to select  ·  Esc to cancel")
        p.end()


# ── EMPTY STATE ───────────────────────────────────────────────────────
class EmptyState(QWidget):
    suggestion_clicked = pyqtSignal(str)

    # Starter prompts: real things the user can type, one per capability mode
    _PROMPTS = [
        "what's on my screen?",
        "search recent AI news",
        "open Spotify",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignVCenter)
        layout.setContentsMargins(18, 36, 18, 28)
        layout.setSpacing(0)

        # Purpose line — three modes, nothing more
        purpose = QLabel("ask, see, open.")
        purpose.setAlignment(Qt.AlignCenter)
        purpose.setStyleSheet(
            f"color: {P.text_muted}; font: 600 12px {_font_stack()};"
        )
        layout.addWidget(purpose)
        layout.addSpacing(22)

        # Clickable starter prompts — look like drafted messages, not feature cards
        for text in self._PROMPTS:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setAccessibleName(f"Try: {text}")
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background: transparent;"
                f"  color: {P.text_muted};"
                f"  border: 1px solid {P.divider};"
                f"  border-radius: 9px;"
                f"  font: 11px {_font_stack()};"
                f"  text-align: left;"
                f"  padding-left: 12px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background: {P.surface};"
                f"  color: {P.text};"
                f"  border-color: {_rgba(P.accent, 70)};"
                f"}}"
                f"QPushButton:pressed {{"
                f"  background: {P.user_bubble};"
                f"  color: {P.text};"
                f"  border-color: {_rgba(P.accent, 110)};"
                f"}}"
            )
            # Default arg capture avoids closure-over-loop pitfall
            btn.clicked.connect(
                lambda checked=False, t=text: self.suggestion_clicked.emit(t)
            )
            layout.addWidget(btn)
            layout.addSpacing(7)

        layout.addSpacing(22)

        shortcut = QLabel("Ctrl+Shift+S to snip your screen")
        shortcut.setAlignment(Qt.AlignCenter)
        shortcut.setStyleSheet(
            f"color: {P.muted_dim}; font: 10px {_font_stack()};"
        )
        layout.addWidget(shortcut)


_ZWS = "​"
_LONG_TOKEN_RE = re.compile(r'\S{25,}')

def _soften_long_tokens(text: str) -> str:
    # QLabel's word-wrap only breaks at whitespace, so an unbroken run (a URL,
    # hash, or pasted string) overflows the bubble instead of wrapping. Insert
    # invisible break points every 24 chars so long tokens still wrap.
    return _LONG_TOKEN_RE.sub(
        lambda m: _ZWS.join(m.group(0)[i:i+24] for i in range(0, len(m.group(0)), 24)),
        text
    )


# ── AVATAR ────────────────────────────────────────────────────────────
_avatar_cache: dict = {}

def _circular_pixmap(path: str, size: int) -> QPixmap:
    key = (path, size)
    cached = _avatar_cache.get(key)
    if cached is not None:
        return cached

    src = QPixmap(path)
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    if not src.isNull():
        src = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addEllipse(0.0, 0.0, float(size), float(size))
        painter.setClipPath(clip)
        x = (size - src.width()) // 2
        y = (size - src.height()) // 2
        painter.drawPixmap(x, y, src)
        painter.end()

    _avatar_cache[key] = result
    return result


# ── ENTRANCE WRAPPER (fade + slide for messages) ─────────────────────
class _SlideInRow(QWidget):
    """Wraps a bubble so it can slide up into place on entrance without
    fighting the outer QVBoxLayout — the slide is done by animating this
    row's own top margin rather than its (layout-managed) position."""

    def __init__(self, inner: QWidget, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._offset = 12
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, self._offset, 0, 0)
        self._layout.setSpacing(0)
        self._layout.addWidget(inner)

    def _get_offset(self): return self._offset
    def _set_offset(self, v):
        self._offset = v
        self._layout.setContentsMargins(0, v, 0, 0)
    offset = pyqtProperty(int, _get_offset, _set_offset)


# ── MESSAGE BUBBLE ────────────────────────────────────────────────────
_BUBBLE_MAX_W = int(PANEL_W * 0.78)

class MessageBubble(QWidget):
    def __init__(self, role: str, text: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        label = QLabel(_soften_long_tokens(text))
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        label.setMaximumWidth(_BUBBLE_MAX_W)
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)

        if role == "user":
            label.setStyleSheet(
                f"background: {P.user_bubble}; color: {P.user_text};"
                f"border: 1px solid {P.user_border};"
                f"border-top-left-radius: 16px; border-top-right-radius: 16px;"
                f"border-bottom-left-radius: 16px; border-bottom-right-radius: 4px;"
                f"padding: 9px 13px; font-family: {_font_stack()}; font-size: 14px;"
            )
            row.addStretch()
            row.addWidget(label)
        else:
            avatar = QLabel()
            avatar.setPixmap(_circular_pixmap(ICON_PATH, 24))
            avatar.setFixedSize(24, 24)
            row.addWidget(avatar, 0, Qt.AlignBottom)

            label.setStyleSheet(
                f"background: {P.surface}; color: {P.text};"
                f"border-top-left-radius: 16px; border-top-right-radius: 16px;"
                f"border-bottom-right-radius: 16px; border-bottom-left-radius: 4px;"
                f"padding: 9px 13px; font-family: {_font_stack()}; font-size: 14px;"
            )
            row.addWidget(label)
            row.addStretch()


# ── TYPING INDICATOR (three pulsing gold stars) ──────────────────────
class StarTypingIndicator(QWidget):
    """Reuses _StarParticle.star_path from kogane_animation to draw three
    small gold stars that pulse in sequence while Kogane is thinking."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(46, 16)
        self._phase = 0.0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._clock.start()
        self._timer.start()
        self.show()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _tick(self):
        self._phase = self._clock.elapsed() / 1000.0
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cy = self.height() / 2.0
        gap = 15
        x0 = 9
        for i in range(3):
            cx = x0 + i * gap
            t = (self._phase * 1.5 - i * 0.3) % 1.0
            op = 0.25 + 0.75 * 0.5 * (1.0 - math.cos(2.0 * math.pi * t))
            color = QColor(P.accent)
            color.setAlphaF(op)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            path = _StarParticle.star_path(cx, cy, 4.5, 0.0)
            p.drawPath(path)
        p.end()


class TypingBubble(QWidget):
    """A Kogane-styled bubble (avatar + rounded surface) that hosts the
    star typing indicator while a response is in flight."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        avatar = QLabel()
        avatar.setPixmap(_circular_pixmap(ICON_PATH, 24))
        avatar.setFixedSize(24, 24)
        row.addWidget(avatar, 0, Qt.AlignBottom)

        bubble = QFrame()
        bubble.setStyleSheet(
            f"background: {P.surface};"
            f"border-top-left-radius: 16px; border-top-right-radius: 16px;"
            f"border-bottom-right-radius: 16px; border-bottom-left-radius: 4px;"
        )
        b_l = QHBoxLayout(bubble)
        b_l.setContentsMargins(14, 12, 14, 12)
        self._stars = StarTypingIndicator()
        b_l.addWidget(self._stars)

        row.addWidget(bubble)
        row.addStretch()

    def start(self): self._stars.start()
    def stop(self):  self._stars.stop()


# ── BUTTON STYLESHEET ─────────────────────────────────────────────────
def _icon_btn_style() -> str:
    return (
        f"QPushButton {{"
        f"  background: {P.surface}; color: {P.text_muted};"
        f"  border-radius: 8px; border: none;"
        f"  font-size: 14px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: {P.accent}; color: {P.accent_text};"
        f"}}"
        f"QPushButton:pressed {{"
        f"  background: {P.accent_press}; color: {P.accent_text};"
        f"}}"
        f"QPushButton:focus {{"
        f"  outline: 2px solid {P.accent}; outline-offset: 1px;"
        f"}}"
    )


# ── PANEL FRAME (Escape-to-close) ─────────────────────────────────────
class _PanelFrame(QFrame):
    """A plain QFrame never actually holds keyboard focus in this app (the
    QTextEdit input does, since it's given focus whenever the panel opens),
    so this keyPressEvent override alone would rarely fire. The real
    mechanism is the QShortcut with WidgetWithChildrenShortcut context set
    up in KoganeWindow._make_panel, which fires regardless of which child
    widget inside the panel currently has focus. This override is kept as
    a direct fallback for the case where the panel itself is focused."""
    escape_pressed = pyqtSignal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(e)


# ── MAIN WINDOW ───────────────────────────────────────────────────────
class KoganeWindow(QWidget):
    _trigger_snip_sig = pyqtSignal()
    _toggle_sig       = pyqtSignal()
    _new_conv_sig     = pyqtSignal()
    _quit_sig         = pyqtSignal()

    _DEFAULT_BOB_SPEED  = kogane_animation.BOB_SPEED
    _THINKING_BOB_SPEED = kogane_animation.BOB_SPEED * 1.8

    def __init__(self):
        super().__init__()
        self._chat_open       = False
        self._locked          = False
        self._last_vision_b64 = None

        self._thread: QThread | None      = None
        self._worker: GroqWorker | None   = None
        self._panel_anim: QParallelAnimationGroup | None = None
        self._send_btn_base_geo: QRect | None = None
        self._send_scale_anim: QPropertyAnimation | None = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)

        self._build_ui()
        self._connect_signals()

        # The panel starts closed — only the floating face widget is visible
        # at launch. Its own [Kogane]-prefixed prints cover load/position/
        # summon diagnostics.
        self.setFixedSize(PANEL_W, PANEL_H)
        self.face_widget.place_bottom_right()
        self.face_widget.summon()

    # ── UI CONSTRUCTION ───────────────────────────────────────────────
    def _build_ui(self):
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(0)

        self._panel = self._make_panel()
        self._panel_fx = QGraphicsOpacityEffect(self._panel)
        self._panel_fx.setOpacity(1.0)
        self._panel.setGraphicsEffect(self._panel_fx)
        self._panel.hide()
        self._root.addWidget(self._panel)

        # Floating icon — a separate always-on-top widget (own summon/dismiss
        # materialize animation with star particles), not embedded in this
        # window's layout.
        self.face_widget = KoganeIconWidget(ICON_PATH)
        self.face_widget.clicked.connect(self._toggle_chat)

        self._selector = RegionSelector()
        self._selector.region_selected.connect(self._on_region_selected)
        self._selector.cancelled.connect(self._on_snip_cancelled)

    def _make_panel(self) -> QFrame:
        panel = _PanelFrame()
        panel.setFixedWidth(PANEL_W)
        # ID selector, not a bare type selector: QLabel, QTextEdit and
        # QScrollArea are all QFrame subclasses in Qt, so "QFrame { ... }"
        # here would cascade this rule into every one of them anywhere in
        # the panel's subtree. Concretely, it collided with the per-corner
        # border-radius longhand set on the message bubble QLabels and on
        # TypingBubble's QFrame — the ancestor's border-radius SHORTHAND
        # conflicting with a descendant's LONGHAND corner properties made
        # Qt drop the radius entirely, rendering square corners instead of
        # either value. #koganePanel matches only this exact widget.
        panel.setObjectName("koganePanel")
        panel.setStyleSheet(
            f"QFrame#koganePanel {{ background: {P.bg}; border-radius: 18px; }}"
        )
        panel.escape_pressed.connect(self._close_panel_animated)

        # Fires regardless of which child widget inside the panel (e.g. the
        # message input) currently has focus — see _PanelFrame docstring.
        esc_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), panel)
        esc_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        esc_shortcut.activated.connect(self._close_panel_animated)
        self._esc_shortcut = esc_shortcut  # keep a ref alive

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # header
        hdr = QWidget()
        hdr.setFixedHeight(58)
        hdr.setStyleSheet("background: transparent;")
        hdr_l = QHBoxLayout(hdr)
        hdr_l.setContentsMargins(16, 0, 12, 0)
        hdr_l.setSpacing(10)

        hdr_avatar = QLabel()
        hdr_avatar.setPixmap(_circular_pixmap(ICON_PATH, 28))
        hdr_avatar.setFixedSize(28, 28)
        hdr_l.addWidget(hdr_avatar)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(1)

        title = QLabel("Kogane")
        title.setStyleSheet(
            f"color: {P.text}; font: 500 15px {_font_stack()};"
        )
        title_col.addWidget(title)

        status = QLabel("online")
        status.setStyleSheet(
            f"color: {P.text_muted}; font: 11px {_font_stack()};"
        )
        title_col.addWidget(status)

        hdr_l.addLayout(title_col)
        hdr_l.addStretch()

        snip_btn = QPushButton("✂")
        snip_btn.setFixedSize(30, 30)
        snip_btn.setToolTip("Screen snip · Ctrl+Shift+S")
        snip_btn.setCursor(Qt.PointingHandCursor)
        snip_btn.setStyleSheet(_icon_btn_style())
        snip_btn.setAccessibleName("Screen snip")
        snip_btn.setAccessibleDescription("Capture a region of the screen for Kogane to analyse. Shortcut: Ctrl+Shift+S")
        snip_btn.clicked.connect(self._start_snip)
        hdr_l.addWidget(snip_btn)

        new_btn = QPushButton("+")
        new_btn.setFixedSize(30, 30)
        new_btn.setToolTip("New conversation")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.setStyleSheet(
            _icon_btn_style() +
            "QPushButton { font-size: 18px; }"
        )
        new_btn.setAccessibleName("New conversation")
        new_btn.setAccessibleDescription("Clear the chat and start a new conversation.")
        new_btn.clicked.connect(self._new_conversation)
        hdr_l.addWidget(new_btn)

        min_btn = QPushButton("⌄")
        min_btn.setFixedSize(30, 30)
        min_btn.setToolTip("Minimize · Esc")
        min_btn.setCursor(Qt.PointingHandCursor)
        min_btn.setAccessibleName("Minimize panel")
        min_btn.setAccessibleDescription(
            "Hide the chat panel. The floating icon stays on screen — click "
            "it, press Ctrl+Space, or Esc to reopen or close."
        )
        min_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: transparent; color: {P.text_muted};"
            f"  border: none; font-size: 16px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: transparent; color: {P.text};"
            f"}}"
            f"QPushButton:pressed {{"
            f"  background: transparent; color: {P.text};"
            f"}}"
            f"QPushButton:focus {{"
            f"  outline: 2px solid {P.accent}; outline-offset: 1px;"
            f"}}"
        )
        min_btn.clicked.connect(self._close_panel_animated)
        hdr_l.addWidget(min_btn)

        layout.addWidget(hdr)

        # divider
        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet(f"color: {P.divider};")
        layout.addWidget(div)

        # scroll area
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
            f"QScrollBar:vertical {{ background: {P.bg}; width: 4px; border: none; }}"
            f"QScrollBar::handle:vertical {{ background: {P.divider}; border-radius: 2px; min-height: 20px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        msg_container = QWidget()
        msg_container.setStyleSheet("background: transparent;")
        self._msg_container = msg_container
        self._msg_layout = QVBoxLayout(msg_container)
        self._msg_layout.setContentsMargins(16, 12, 16, 12)
        self._msg_layout.setSpacing(12)

        self._empty_state = EmptyState()
        self._empty_state.suggestion_clicked.connect(self._fill_input)
        self._msg_layout.addWidget(self._empty_state)
        self._msg_layout.addStretch()

        self._typing_bubble = TypingBubble()
        thinking_row = QHBoxLayout()
        thinking_row.setContentsMargins(0, 0, 0, 0)
        thinking_row.addWidget(self._typing_bubble)
        thinking_wrap = QWidget()
        thinking_wrap.setAttribute(Qt.WA_TranslucentBackground)
        thinking_wrap.setLayout(thinking_row)
        thinking_wrap.hide()
        self._msg_layout.addWidget(thinking_wrap)
        self._thinking_wrap = thinking_wrap

        self._scroll.setWidget(msg_container)
        layout.addWidget(self._scroll, 1)

        # divider above input bar
        div2 = QFrame()
        div2.setFrameShape(QFrame.HLine)
        div2.setStyleSheet(f"color: {P.divider};")
        layout.addWidget(div2)

        # input bar
        input_bar = QWidget()
        input_bar.setStyleSheet("background: transparent;")
        input_bar.setFixedHeight(64)
        input_l = QHBoxLayout(input_bar)
        input_l.setContentsMargins(16, 10, 16, 12)
        input_l.setSpacing(8)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Ask anything…")
        self._input.setFixedHeight(42)
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._input.setAccessibleName("Message to Kogane")
        self._input.setAccessibleDescription(
            "Type your message. Press Enter to send, Shift+Enter for a new line."
        )
        self._input.setStyleSheet(
            f"QTextEdit {{"
            f"  background: {P.surface}; color: {P.text};"
            f"  border-radius: 12px; padding: 8px 12px;"
            f"  font: 14px {_font_stack()}; border: 1px solid {P.surface_border};"
            f"}}"
            f"QTextEdit:focus {{"
            f"  border: 1px solid {P.accent};"
            f"}}"
        )
        pal = self._input.palette()
        pal.setColor(QPalette.PlaceholderText, QColor(P.text_muted))
        self._input.setPalette(pal)
        self._input.installEventFilter(self)
        input_l.addWidget(self._input)

        send_btn = QPushButton("↑")
        send_btn.setFixedSize(42, 42)
        send_btn.setCursor(Qt.PointingHandCursor)
        send_btn.setAccessibleName("Send message")
        send_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {P.accent}; color: {P.accent_text};"
            f"  border-radius: 12px; font-size: 18px; font-weight: bold; border: none;"
            f"}}"
            f"QPushButton:hover {{ background: {P.accent_hover}; }}"
            f"QPushButton:pressed {{ background: {P.accent_press}; }}"
            f"QPushButton:focus {{ outline: 2px solid {P.accent}; outline-offset: 2px; }}"
            f"QPushButton:disabled {{ background: {P.surface}; color: {P.muted_dim}; }}"
        )
        send_btn.clicked.connect(self._on_send)
        send_btn.pressed.connect(self._on_send_btn_pressed)
        send_btn.released.connect(self._on_send_btn_released)
        self._send_btn = send_btn
        input_l.addWidget(send_btn)

        layout.addWidget(input_bar)
        return panel

    def _connect_signals(self):
        self._trigger_snip_sig.connect(self._start_snip)
        self._toggle_sig.connect(self._toggle_visibility)
        self._new_conv_sig.connect(self._new_conversation)
        self._quit_sig.connect(self._do_quit)

    # ── ASYNC HELPER (Task 1: thread-safe Groq calls) ─────────────────
    def _run_async(self, fn, on_result, on_error):
        self._cleanup_worker()

        thread = QThread(self)
        worker = GroqWorker(fn)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.response_ready.connect(on_result)
        worker.error.connect(on_error)
        worker.response_ready.connect(thread.quit)
        worker.error.connect(thread.quit)
        worker.response_ready.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup_worker(self):
        if self._thread is not None:
            try:
                if self._thread.isRunning():
                    self._thread.quit()
                    self._thread.wait(2000)
            except RuntimeError:
                pass
        self._thread = None
        self._worker = None

    # ── PANEL OPEN / CLOSE (Task 3.1 / 3.2) ────────────────────────────
    def _panel_target_pos(self) -> QPoint:
        # Anchor the panel's bottom-right corner to the *visible* icon inside
        # face_widget's padded canvas (WIDGET_SIZE includes room for star
        # particles; ICON_SIZE is the actual drawn icon).
        icon_geo = self.face_widget.geometry()
        pad = (WIDGET_SIZE - ICON_SIZE) // 2
        anchor_x = icon_geo.right()  - pad
        anchor_y = icon_geo.top()    + pad
        new_x = anchor_x - PANEL_W
        new_y = anchor_y - PANEL_H - 6
        screen = QApplication.primaryScreen().availableGeometry()
        new_x = max(screen.left(), min(new_x, screen.right()  - PANEL_W))
        new_y = max(screen.top(),  min(new_y, screen.bottom() - PANEL_H))
        return QPoint(new_x, new_y)

    def _open_panel_animated(self):
        if self._chat_open:
            return
        if (self._panel_anim
                and self._panel_anim.state() == QAbstractAnimation.Running):
            return
        self._chat_open = True

        final_pos = self._panel_target_pos()
        start_pos = QPoint(final_pos.x(), final_pos.y() + 24)

        self._panel_fx.setOpacity(0.0)
        self._panel.show()
        self.move(start_pos)
        self.show()
        self.raise_()
        self._input.setFocus()

        # The icon is a permanent anchor for the whole app session. It's
        # already visible in the overwhelming majority of cases (nothing
        # in the panel open/close path ever dismisses it any more); this
        # only re-summons it if something else — e.g. its own built-in
        # right-click-to-dismiss gesture in kogane_animation.py — hid it.
        if not self.face_widget.isVisible():
            self.face_widget.summon()

        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(final_pos)
        pos_anim.setDuration(220)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        fade_anim = QPropertyAnimation(self._panel_fx, b"opacity")
        fade_anim.setStartValue(0.0)
        fade_anim.setEndValue(1.0)
        fade_anim.setDuration(220)
        fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)
        group.start()
        self._panel_anim = group

    def _close_panel_animated(self):
        if not self._chat_open:
            return
        if (self._panel_anim
                and self._panel_anim.state() == QAbstractAnimation.Running):
            return
        self._chat_open = False

        start_pos = self.pos()
        end_pos = QPoint(start_pos.x(), start_pos.y() + 16)

        pos_anim = QPropertyAnimation(self, b"pos")
        pos_anim.setStartValue(start_pos)
        pos_anim.setEndValue(end_pos)
        pos_anim.setDuration(160)
        pos_anim.setEasingCurve(QEasingCurve.OutCubic)

        fade_anim = QPropertyAnimation(self._panel_fx, b"opacity")
        fade_anim.setStartValue(self._panel_fx.opacity())
        fade_anim.setEndValue(0.0)
        fade_anim.setDuration(160)
        fade_anim.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(self)
        group.addAnimation(pos_anim)
        group.addAnimation(fade_anim)

        def _after():
            self._panel.hide()
            self.hide()
            # Deliberately does NOT call face_widget.dismiss() — the icon
            # is a permanent anchor and only disappears on full app exit
            # (see _do_quit) or via its own right-click gesture.

        group.finished.connect(_after)
        group.start()
        self._panel_anim = group

    def _toggle_chat(self):
        # Click on the floating icon: toggle the panel open/closed. The
        # icon itself is never summoned/dismissed from this path.
        if self._chat_open:
            self._close_panel_animated()
        else:
            self._open_panel_animated()

    # ── MESSAGING ─────────────────────────────────────────────────────
    def _add_message(self, role: str, text: str):
        # Diagnostic evidence for the "blank until click" report: if this
        # ever printed a worker/background thread id instead of the main
        # thread id, that would mean a widget was being touched off the
        # GUI thread. Kept permanently (cheap) so future regressions show
        # up immediately in the console.
        print("[Kogane] add_bubble on thread:", QThread.currentThread(),
              "| main thread:", QApplication.instance().thread(), flush=True)

        if self._empty_state.isVisible():
            self._empty_state.hide()

        bubble = MessageBubble(role, text)
        row = _SlideInRow(bubble)

        fx = QGraphicsOpacityEffect(row)
        fx.setOpacity(0.0)
        row.setGraphicsEffect(fx)

        self._msg_layout.insertWidget(self._msg_layout.count() - 1, row)

        fade = QPropertyAnimation(fx, b"opacity")
        fade.setStartValue(0.0); fade.setEndValue(1.0)
        fade.setDuration(180); fade.setEasingCurve(QEasingCurve.OutCubic)

        slide = QPropertyAnimation(row, b"offset")
        slide.setStartValue(12); slide.setEndValue(0)
        slide.setDuration(180); slide.setEasingCurve(QEasingCurve.OutCubic)

        group = QParallelAnimationGroup(row)
        group.addAnimation(fade)
        group.addAnimation(slide)
        group.start()
        row._entrance_anim = group  # keep ref alive — GC'd with the row

        # Force the layout and the (translucent, layered) top-level window
        # to actually flush a repaint right now rather than waiting for the
        # next natural paint event — on a frameless WA_TranslucentBackground
        # window, a child added from a queued/cross-thread-originated call
        # can otherwise sit correctly in the layout but not be composited
        # onto the native surface until something else (e.g. a click)
        # forces Windows to repaint it.
        row.show()
        self._msg_layout.activate()
        self._msg_container.adjustSize()
        self._scroll.widget().updateGeometry()
        QApplication.processEvents()
        self._panel.update()
        self.update()

        self._scroll_to_bottom()
        QTimer.singleShot(50, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self._scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _fill_input(self, text: str):
        self._input.setPlainText(text)
        self._input.setFocus()
        self._input.moveCursor(QTextCursor.End)

    def _set_thinking(self, on: bool):
        self._locked = on
        self._send_btn.setEnabled(not on)
        if on:
            self._thinking_wrap.show()
            self._typing_bubble.start()
            kogane_animation.BOB_SPEED = self._THINKING_BOB_SPEED
        else:
            self._typing_bubble.stop()
            self._thinking_wrap.hide()
            kogane_animation.BOB_SPEED = self._DEFAULT_BOB_SPEED
        QTimer.singleShot(30, self._scroll_to_bottom)

    _MAX_INPUT = 4000

    def _on_send(self):
        text = self._input.toPlainText().strip()
        if not text or self._locked:
            return
        if len(text) > self._MAX_INPUT:
            text = text[:self._MAX_INPUT]
        self._input.clear()
        self._dispatch(text)

    # ── SEND BUTTON MICRO-INTERACTION (Task 3.5) ───────────────────────
    def _on_send_btn_pressed(self):
        if self._send_btn_base_geo is None:
            self._send_btn_base_geo = self._send_btn.geometry()
        self._animate_send_btn_scale(0.92)

    def _on_send_btn_released(self):
        self._animate_send_btn_scale(1.0)

    def _animate_send_btn_scale(self, factor: float):
        base = self._send_btn_base_geo or self._send_btn.geometry()
        w = base.width() * factor
        h = base.height() * factor
        x = base.x() + (base.width() - w) / 2
        y = base.y() + (base.height() - h) / 2
        target = QRect(round(x), round(y), round(w), round(h))

        anim = QPropertyAnimation(self._send_btn, b"geometry")
        anim.setDuration(90)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.setEndValue(target)
        anim.start()
        self._send_scale_anim = anim

    def _dispatch(self, text: str):
        global _active_conv_id
        if _active_conv_id is None:
            _active_conv_id = db_new_conversation(_make_title(text))
        db_append("user", text)
        self._add_message("user", text)
        self._set_thinking(True)

        if self._last_vision_b64:
            b64 = self._last_vision_b64
            self._last_vision_b64 = None
            fn = lambda: ask_groq_with_image(text, b64)
        else:
            fn = lambda: ask_groq(text)

        self._run_async(fn, self._on_reply, self._on_error)

    def _on_reply(self, reply: str):
        # Keep locked during SCREEN flow — snip completion will unlock
        if reply.strip() == "SCREEN":
            self._start_snip()
            return

        self._set_thinking(False)

        if reply.startswith("OPEN:"):
            name = reply[5:].strip()
            db_append("assistant", reply)
            try:
                subprocess.Popen(name)
                self._add_message("ai", f"Opening {name}…")
            except Exception:
                self._add_message("ai", f"Could not open {name}")
            return

        if reply.startswith("SEARCH:"):
            query = reply[7:].strip()
            try:
                webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
            except Exception:
                pass
            db_append("assistant", reply)
            self._add_message("ai", f"Searching: {query}")
            return

        db_append("assistant", reply)
        self._add_message("ai", reply)

    def _on_error(self, msg: str):
        self._set_thinking(False)
        self._add_message("ai", msg)

    def _new_conversation(self):
        global _active_conv_id
        _active_conv_id = None
        conversation_history.clear()
        self._last_vision_b64 = None
        # Layout: [0]=empty_state, [1]=stretch, [2..N-2]=bubbles, [N-1]=thinking_wrap
        # Remove bubbles at index 2 until only 3 items remain.
        while self._msg_layout.count() > 3:
            item = self._msg_layout.takeAt(2)
            if item.widget():
                item.widget().deleteLater()
        self._empty_state.show()

    # ── SCREEN SNIP ───────────────────────────────────────────────────
    def _start_snip(self):
        if self._locked:
            # A request is already in flight — starting a snip now would spin
            # up a second worker whose signals race with the first one.
            return
        if not self._chat_open:
            self._open_panel_animated()
        self.hide()
        self.face_widget.hide()  # keep Kogane out of her own screenshot
        QTimer.singleShot(200, self._selector.activate)

    def _on_snip_cancelled(self):
        self._set_thinking(False)
        self.show()
        self.face_widget.show()

    def _on_region_selected(self, x1, y1, x2, y2):
        self.show()
        self.face_widget.show()
        self._set_thinking(True)
        self._add_message("user", "screen capture")

        def capture():
            b64 = screen_to_b64(region=(x1, y1, x2, y2))
            return ask_groq_vision(b64)

        self._run_async(capture, self._on_snip_result, self._on_error)

    def _on_snip_result(self, reply: str):
        global _active_conv_id
        if _active_conv_id is None:
            _active_conv_id = db_new_conversation("Screen reading")
        db_append("assistant", reply)
        self._last_vision_b64 = None
        self._set_thinking(False)
        self._add_message("ai", reply)

    # ── VISIBILITY TOGGLE (Ctrl+Space / tray) ──────────────────────────
    def _toggle_visibility(self):
        # This is invoked from the global OS-level hotkey hook (see
        # _hotkey_thread) and the tray "Show / Hide" item — both reach it
        # only through the _toggle_sig queued signal, never a direct call,
        # so it works regardless of which window/widget currently has
        # keyboard focus. It only opens/closes the panel; the floating
        # icon is a permanent anchor and is never dismissed here.
        if self._chat_open:
            self._close_panel_animated()
        else:
            self._open_panel_animated()

    def _do_quit(self):
        # The only place the icon is allowed to actually disappear: a full
        # app exit. Give its dismiss animation a moment to play before the
        # process actually terminates.
        self.face_widget.dismiss()
        QTimer.singleShot(400, QApplication.quit)

    # ── EVENT FILTER (Enter key in input) ─────────────────────────────
    def eventFilter(self, obj, event):
        from PyQt5.QtCore import QEvent
        if obj is self._input and event.type() == QEvent.KeyPress:
            if (event.key() in (Qt.Key_Return, Qt.Key_Enter)
                    and not (event.modifiers() & Qt.ShiftModifier)):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def paintEvent(self, _):
        pass


# ── SYSTEM TRAY ───────────────────────────────────────────────────────
def _setup_tray(window: KoganeWindow):
    try:
        img = PILImage.open(ICON_PATH).convert("RGBA")
    except Exception:
        img = PILImage.new("RGBA", (64, 64), (232, 168, 37, 255))

    menu = pystray.Menu(
        pystray.MenuItem("Show / Hide",      lambda: window._toggle_sig.emit()),
        pystray.MenuItem("Screen snip",      lambda: window._trigger_snip_sig.emit()),
        pystray.MenuItem("New conversation", lambda: window._new_conv_sig.emit()),
        pystray.MenuItem("Quit",             lambda: window._quit_sig.emit()),
    )
    icon = pystray.Icon("Kogane", img, "Kogane", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


# ── HOTKEYS ───────────────────────────────────────────────────────────
def _hotkey_thread(window: KoganeWindow):
    try:
        keyboard.add_hotkey(HOTKEY,      lambda: window._toggle_sig.emit())
        keyboard.add_hotkey(HOTKEY_SNIP, lambda: window._trigger_snip_sig.emit())
    except Exception as exc:
        print(f"[Kogane] hotkey registration failed: {exc}", flush=True)
        return
    keyboard.wait()


# ── KEY SETUP ─────────────────────────────────────────────────────────
def _show_key_dialog() -> str:
    try:
        import tkinter as tk
        from tkinter import simpledialog
        root = tk.Tk(); root.withdraw()
        root.attributes("-topmost", True)
        key = simpledialog.askstring(
            "Kogane — Setup",
            "GROQ_API_KEY not set.\n\nPaste your Groq API key:",
            parent=root,
        )
        root.destroy()
        return (key or "").strip()
    except Exception as exc:
        print(f"[Kogane] key dialog error: {exc}", flush=True)
        return ""

def _save_key_to_env(key: str):
    env_path = os.path.join(BASE_DIR, ".env")
    lines = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            lines = f.readlines()
    lines = [l for l in lines if not l.startswith("GROQ_API_KEY=")]
    lines.insert(0, f"GROQ_API_KEY={key}\n")
    with open(env_path, "w") as f:
        f.writelines(lines)


# ── ENTRY POINT ───────────────────────────────────────────────────────
def main():
    global groq_client, FONT_FAMILY

    api_key = GROQ_API_KEY
    if not api_key:
        api_key = _show_key_dialog()
        if not api_key:
            print("[Kogane] No API key — exiting", flush=True)
            sys.exit(1)
        _save_key_to_env(api_key)

    groq_client = Groq(api_key=api_key)

    # HiDPI: must be set before QApplication is created
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    FONT_FAMILY = _load_font_family()

    window = KoganeWindow()
    _setup_tray(window)
    threading.Thread(target=_hotkey_thread, args=(window,), daemon=True).start()

    sys.exit(app.exec_())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("\n[Kogane] FATAL:\n", flush=True)
        traceback.print_exc()
        try: input("Press Enter to exit…")
        except Exception: pass
        sys.exit(1)
