"""
kogane_animation.py — Animated floating icon widget for Kogane
================================================================
Drop-in replacement for the plain icon widget.

Features:
  1. MATERIALIZE (summon) animation — icon scales up from nothing with a
     bouncy overshoot, fades in, and bursts blue star particles outward.
  2. DISMISS animation — icon shrinks and fades out with a small particle puff.
  3. IDLE BOB — gentle floating up/down motion while visible (Kogane hovers).
  4. Loud debug prints + try/except around all drawing so nothing fails silently.

Run standalone to test:
    python kogane_animation.py
    (Click the icon to replay the summon animation. Right-click to dismiss.)

Integrate into kogane.py:
    from kogane_animation import KoganeIconWidget
    self.face_widget = KoganeIconWidget("kogane.png")
    self.face_widget.place_bottom_right()
    self.face_widget.summon()          # play materialize animation
    self.face_widget.clicked.connect(self.toggle_panel)   # open panel on click
"""

import json
import math
import os
import random
import sys
import traceback

from PyQt5.QtCore import Qt, QTimer, QPoint, QPointF, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtGui import QPainter, QPixmap, QColor, QPainterPath, QPen

try:
    from PIL import Image as _PILImage
except Exception:
    _PILImage = None
from PyQt5.QtWidgets import QApplication, QWidget


# ----------------------------------------------------------------------------
# Tunables — tweak these to taste
# ----------------------------------------------------------------------------
ICON_SIZE = 72            # visible icon size in px
WIDGET_SIZE = 160         # widget canvas (bigger than icon so particles fit)
FPS = 60                  # animation frame rate
SUMMON_DURATION = 0.55    # seconds for the materialize scale/fade
DISMISS_DURATION = 0.30   # seconds for the shrink/fade out
PARTICLE_COUNT = 14       # stars per burst
PARTICLE_LIFE = 0.7       # seconds each star lives
BOB_AMPLITUDE = 4.0       # px of idle up/down float
BOB_SPEED = 2.0           # idle bob cycles per ~3 seconds

BOUNCE_HOPS = 2           # number of hops played by bounce()
BOUNCE_HOP_DURATION = 0.25  # seconds per hop
BOUNCE_HEIGHT = 14.0      # px, upward hop offset added on top of idle bob

SHAKE_DURATION = 0.40     # seconds, decaying horizontal oscillation
SHAKE_AMPLITUDE = 4.0     # px, initial horizontal offset
SHAKE_FREQ = 9.0          # oscillations per second

POS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kogane_pos.json")
DRAG_THRESHOLD = 8   # px of movement before a press becomes a drag
GAZE_RANGE_PX = 260      # cursor distance for full pupil deflection
GAZE_SMOOTHING = 0.18    # lerp factor per frame (lower = lazier eyes)
PUPIL_COLOR = QColor(66, 133, 244)

STAR_COLORS = [
    QColor(66, 133, 244),   # Kogane blue (matches the eyes/horns)
    QColor(120, 170, 255),
    QColor(200, 220, 255),
    QColor(255, 255, 255),
]


def ease_out_back(t: float) -> float:
    """Easing with overshoot — gives the icon a springy 'pop' on summon."""
    c1 = 1.70158
    c3 = c1 + 1
    return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2


def ease_in_cubic(t: float) -> float:
    return t * t * t


def _setup_gaze(icon_path: str):
    """Detect the pupils in the icon, build a pupil-less base image, and
    return the eye geometry so pupils can be repainted live, aimed at the
    cursor. Returns None if anything fails — the icon then renders
    statically, exactly as before."""
    if _PILImage is None:
        print("[Kogane] gaze disabled: Pillow not available")
        return None
    try:
        img = _PILImage.open(icon_path).convert("RGBA")
        W, H = img.size
        px = img.load()

        def lum(x, y):
            r, g, b, a = px[x, y]
            return (r + g + b) / 3 if a > 200 else 255

        blue = [(x, y) for y in range(H) for x in range(W)
                if (lambda r, g, b, a: a > 200 and b > 150
                    and b - r > 60 and b - g > 40)(*px[x, y])]
        if not blue:
            return None

        CELL = 8
        cells = {}
        for x, y in blue:
            cells.setdefault((x // CELL, y // CELL), []).append((x, y))
        parent = {c: c for c in cells}

        def find(c):
            while parent[c] != c:
                parent[c] = parent[parent[c]]
                c = parent[c]
            return c

        for (cx, cy) in list(cells):
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (cx + dx, cy + dy)
                    if n in cells:
                        ra, rb = find((cx, cy)), find(n)
                        if ra != rb:
                            parent[ra] = rb
        clusters = {}
        for c, pts in cells.items():
            clusters.setdefault(find(c), []).extend(pts)

        candidates = []
        for pts in clusters.values():
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            pr = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
            dark = total = 0
            for ang in range(0, 360, 20):
                sx = int(cx + math.cos(math.radians(ang)) * pr * 2.2)
                sy = int(cy + math.sin(math.radians(ang)) * pr * 2.2)
                if 0 <= sx < W and 0 <= sy < H:
                    total += 1
                    if lum(sx, sy) < 80:
                        dark += 1
            if total and dark / total > 0.6:   # pupil sits inside a dark eye
                candidates.append((len(pts), cx, cy, pr))

        eyes_raw = sorted(candidates, key=lambda i: -i[0])[:2]
        if len(eyes_raw) != 2:
            return None
        eyes_raw = sorted(eyes_raw, key=lambda i: i[1])   # left, right

        eyes = []
        for _, cx, cy, pr in eyes_raw:
            dists = []
            for ang in range(0, 360, 15):
                d = pr
                while d < 80:
                    sx = int(cx + math.cos(math.radians(ang)) * d)
                    sy = int(cy + math.sin(math.radians(ang)) * d)
                    if not (0 <= sx < W and 0 <= sy < H) or lum(sx, sy) >= 80:
                        break
                    d += 1
                dists.append(d)
            er = sum(dists) / len(dists)
            eyes.append((cx, cy, pr, er))

        # paint the pupils out with the surrounding eye color
        base = img.copy()
        bpx = base.load()
        for cx, cy, pr, er in eyes:
            sx = min(W - 1, int(cx + pr + 3))
            eye_color = px[sx, int(cy)]
            rr = int(pr + 2)
            for dy in range(-rr, rr + 1):
                for dx in range(-rr, rr + 1):
                    if dx * dx + dy * dy <= rr * rr:
                        tx, ty = int(cx) + dx, int(cy) + dy
                        if 0 <= tx < W and 0 <= ty < H:
                            bpx[tx, ty] = eye_color

        base_path = os.path.join(
            os.path.dirname(os.path.abspath(icon_path)), "kogane_base_gen.png")
        base.save(base_path)
        print(f"[Kogane] gaze ready: eyes at "
              f"{[(int(e[0]), int(e[1])) for e in eyes]} (source {W}x{H})")
        return {"base_path": base_path, "eyes": eyes, "size": (W, H)}
    except Exception:
        print("[Kogane] gaze setup failed — static icon fallback:")
        traceback.print_exc()
        return None


class _StarParticle:
    """A single 5-point star flying outward from the icon center."""

    def __init__(self, cx: float, cy: float):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(45, 130)          # px per second
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - 20   # slight upward bias
        self.x = cx
        self.y = cy
        self.size = random.uniform(3.5, 8.0)
        self.spin = random.uniform(-360, 360)    # degrees per second
        self.rotation = random.uniform(0, 360)
        self.age = 0.0
        self.life = PARTICLE_LIFE * random.uniform(0.7, 1.15)
        self.color = random.choice(STAR_COLORS)

    def update(self, dt: float) -> bool:
        """Advance physics. Returns False when the particle is dead."""
        self.age += dt
        if self.age >= self.life:
            return False
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vy += 30 * dt                        # gentle gravity
        self.rotation += self.spin * dt
        return True

    def opacity(self) -> float:
        t = self.age / self.life
        return max(0.0, 1.0 - t * t)              # fade out toward end of life

    @staticmethod
    def star_path(cx: float, cy: float, size: float, rotation_deg: float) -> QPainterPath:
        """Build a 5-point star QPainterPath centered at (cx, cy)."""
        path = QPainterPath()
        points = 5
        outer = size
        inner = size * 0.45
        rot = math.radians(rotation_deg) - math.pi / 2
        for i in range(points * 2):
            r = outer if i % 2 == 0 else inner
            a = rot + i * math.pi / points
            px = cx + math.cos(a) * r
            py = cy + math.sin(a) * r
            if i == 0:
                path.moveTo(QPointF(px, py))
            else:
                path.lineTo(QPointF(px, py))
        path.closeSubpath()
        return path


class KoganeIconWidget(QWidget):
    """Frameless, always-on-top floating icon with summon/dismiss animations."""

    clicked = pyqtSignal()      # emitted on left-click (hook your panel toggle here)
    dismissed = pyqtSignal()    # emitted after the dismiss animation finishes
    moved = pyqtSignal(int, int)  # emitted after the icon is dragged to a new spot

    def __init__(self, icon_path: str = "kogane.png", parent=None):
        super().__init__(parent)

        # --- Window flags: frameless, on top, transparent, no taskbar entry ---
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                      # Tool = no taskbar button
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)

        # --- Load icon with a guaranteed fallback ---
        self.pixmap = QPixmap(icon_path)
        if self.pixmap.isNull():
            print(f"[Kogane] WARNING: could not load '{icon_path}' — using fallback circle")
            self.pixmap = None
        else:
            print(f"[Kogane] Icon loaded: {icon_path} "
                  f"({self.pixmap.width()}x{self.pixmap.height()})")

        # --- Animation state ---
        self.state = "hidden"        # hidden | summoning | idle | dismissing
        self.anim_t = 0.0            # 0..1 progress through summon/dismiss
        self.scale = 0.0
        self.alpha = 0.0
        self.bob_phase = 0.0
        self.particles: list[_StarParticle] = []

        # --- Micro-animation state (bounce/shake) ---
        self._bounce_active = False
        self._bounce_t = 0.0
        self._shake_active = False
        self._shake_t = 0.0

        self.timer = QTimer(self)
        self.timer.setInterval(int(1000 / FPS))
        self.timer.timeout.connect(self._tick)

        # --- Gaze (eyes follow the cursor) ---
        self._gaze = None
        self._gaze_base = None
        self._gaze_cur = QPointF(0.0, 0.0)     # smoothed pupil offset (-1..1)
        self.gaze_override = None              # QPoint global pos, for demos
        if self.pixmap is not None:
            self._gaze = _setup_gaze(icon_path)
            if self._gaze:
                self._gaze_base = QPixmap(self._gaze["base_path"])
                if self._gaze_base.isNull():
                    self._gaze = None

        # --- Drag state ---
        self._press_global = QPoint()
        self._press_widget_pos = QPoint()
        self._dragging = False
        self.setCursor(Qt.OpenHandCursor)

        print("[Kogane] Icon widget created")

    # ------------------------------------------------------------------ API
    def place_bottom_right(self, margin_x: int = 40, margin_y: int = 90):
        """Position at the last dragged spot if one is saved, otherwise
        default to the bottom-right corner above the taskbar."""
        saved = self._load_saved_position()
        if saved is not None:
            self.move(saved[0], saved[1])
            print(f"[Kogane] Restored saved position ({saved[0]}, {saved[1]})")
            return
        screen = QApplication.primaryScreen().availableGeometry()
        x = screen.right() - WIDGET_SIZE - margin_x
        y = screen.bottom() - WIDGET_SIZE - margin_y
        self.move(x, y)
        print(f"[Kogane] Positioned at ({x}, {y}) on screen "
              f"{screen.width()}x{screen.height()}")

    def summon(self):
        """Play the materialize animation (scale up + fade in + star burst)."""
        print("[Kogane] SUMMON animation starting")
        self.state = "summoning"
        self.anim_t = 0.0
        self.scale = 0.0
        self.alpha = 0.0
        cx, cy = WIDGET_SIZE / 2, WIDGET_SIZE / 2
        self.particles = [_StarParticle(cx, cy) for _ in range(PARTICLE_COUNT)]
        self.show()
        self.raise_()
        if not self.timer.isActive():
            self.timer.start()
            print(f"[Kogane] Animation timer started ({FPS} fps)")

    def dismiss(self):
        """Play the shrink/fade-out animation, then hide."""
        if self.state in ("hidden", "dismissing"):
            return
        print("[Kogane] DISMISS animation starting")
        self.state = "dismissing"
        self.anim_t = 0.0
        cx, cy = WIDGET_SIZE / 2, WIDGET_SIZE / 2
        self.particles += [_StarParticle(cx, cy) for _ in range(PARTICLE_COUNT // 2)]

    def bounce(self):
        """Two quick upward hops — draws attention (e.g. a reminder firing).
        No-op unless idle: never interrupts a drag, or a summon/dismiss
        already in flight."""
        if self.state != "idle" or self._dragging:
            return
        self._bounce_active = True
        self._bounce_t = 0.0

    def shake(self):
        """A short, decaying horizontal shake — signals an error.
        No-op unless idle: never interrupts a drag, or a summon/dismiss
        already in flight."""
        if self.state != "idle" or self._dragging:
            return
        self._shake_active = True
        self._shake_t = 0.0

    # ------------------------------------------------------------ animation
    def _tick(self):
        dt = 1.0 / FPS
        try:
            if self.state != "idle":
                # micro-animations only ever play while idle — cancel
                # cleanly if a summon/dismiss took over mid-flight.
                self._bounce_active = False
                self._shake_active = False

            if self.state == "summoning":
                self.anim_t = min(1.0, self.anim_t + dt / SUMMON_DURATION)
                self.scale = ease_out_back(self.anim_t)
                self.alpha = min(1.0, self.anim_t * 2.5)
                if self.anim_t >= 1.0:
                    self.state = "idle"
                    print("[Kogane] Summon complete -> idle")

            elif self.state == "idle":
                self.bob_phase += dt * BOB_SPEED
                self.scale = 1.0
                self.alpha = 1.0

                if self._bounce_active:
                    self._bounce_t += dt
                    if self._bounce_t >= BOUNCE_HOPS * BOUNCE_HOP_DURATION:
                        self._bounce_active = False

                if self._shake_active:
                    self._shake_t += dt
                    if self._shake_t >= SHAKE_DURATION:
                        self._shake_active = False

            elif self.state == "dismissing":
                self.anim_t = min(1.0, self.anim_t + dt / DISMISS_DURATION)
                self.scale = 1.0 - ease_in_cubic(self.anim_t)
                self.alpha = 1.0 - self.anim_t
                if self.anim_t >= 1.0 and not self.particles:
                    self.state = "hidden"
                    self.timer.stop()
                    self.hide()
                    print("[Kogane] Dismiss complete -> hidden")
                    self.dismissed.emit()

            # gaze: ease pupils toward the cursor direction
            if self._gaze is not None and self.state in ("idle", "summoning"):
                cursor = self.gaze_override or QCursor.pos()
                center = self.mapToGlobal(
                    QPoint(WIDGET_SIZE // 2, WIDGET_SIZE // 2))
                dx = cursor.x() - center.x()
                dy = cursor.y() - center.y()
                dist = math.hypot(dx, dy)
                if dist > 1:
                    mag = min(1.0, dist / GAZE_RANGE_PX)
                    tx, ty = dx / dist * mag, dy / dist * mag
                else:
                    tx = ty = 0.0
                self._gaze_cur += (QPointF(tx, ty) - self._gaze_cur) * GAZE_SMOOTHING

            # advance particles
            self.particles = [p for p in self.particles if p.update(dt)]
            self.update()  # trigger repaint

        except Exception:
            print("[Kogane] ERROR in animation tick:")
            traceback.print_exc()

    # -------------------------------------------------------------- painting
    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            cx, cy = WIDGET_SIZE / 2, WIDGET_SIZE / 2
            bob = 0.0
            shake_x = 0.0
            if self.state == "idle":
                bob = math.sin(self.bob_phase * math.pi) * BOB_AMPLITUDE
                if self._bounce_active:
                    phase = (self._bounce_t % BOUNCE_HOP_DURATION) / BOUNCE_HOP_DURATION
                    bob += -BOUNCE_HEIGHT * math.sin(math.pi * phase)
                if self._shake_active:
                    decay = max(0.0, 1.0 - self._shake_t / SHAKE_DURATION)
                    shake_x = (SHAKE_AMPLITUDE * decay
                               * math.sin(2 * math.pi * SHAKE_FREQ * self._shake_t))

            # --- glow behind the icon while summoning ---
            if self.state == "summoning" and self.scale > 0.1:
                glow_r = ICON_SIZE * 0.75 * self.scale
                glow = QColor(66, 133, 244)
                glow.setAlphaF(0.25 * self.alpha * (1.0 - self.anim_t))
                painter.setBrush(glow)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(cx, cy + bob), glow_r, glow_r)

            # --- the icon itself ---
            if self.scale > 0.01 and self.alpha > 0.01:
                painter.setOpacity(self.alpha)
                size = ICON_SIZE * max(0.0, self.scale)
                if self.pixmap is not None:
                    source = self._gaze_base if self._gaze is not None else self.pixmap
                    scaled = source.scaled(
                        int(size), int(size),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation,
                    )
                    left = cx - scaled.width() / 2 + shake_x
                    top  = cy - scaled.height() / 2 + bob
                    painter.drawPixmap(int(left), int(top), scaled)
                    if self._gaze is not None:
                        s = scaled.width() / self._gaze["size"][0]
                        painter.setPen(Qt.NoPen)
                        painter.setBrush(PUPIL_COLOR)
                        for ecx, ecy, pr, er in self._gaze["eyes"]:
                            max_off = max(0.0, (er - pr)) * 0.7 * s
                            pxp = left + ecx * s + self._gaze_cur.x() * max_off
                            pyp = top  + ecy * s + self._gaze_cur.y() * max_off
                            painter.drawEllipse(QPointF(pxp, pyp), pr * s, pr * s)
                else:
                    # fallback: plain white circle with blue eyes
                    painter.setBrush(QColor(245, 245, 245))
                    painter.setPen(Qt.NoPen)
                    painter.drawEllipse(QPointF(cx + shake_x, cy + bob), size / 2, size / 2)
                painter.setOpacity(1.0)

            # --- star particles ---
            for p in self.particles:
                try:
                    color = QColor(p.color)
                    color.setAlphaF(p.opacity())
                    painter.setBrush(color)
                    painter.setPen(Qt.NoPen)
                    path = _StarParticle.star_path(p.x, p.y, p.size, p.rotation)
                    painter.drawPath(path)
                except Exception:
                    print("[Kogane] ERROR drawing particle:")
                    traceback.print_exc()

            painter.end()
        except Exception:
            print("[Kogane] ERROR in paintEvent:")
            traceback.print_exc()

    # ------------------------------------------------------- position memory
    def _load_saved_position(self):
        try:
            if os.path.exists(POS_FILE):
                with open(POS_FILE) as f:
                    data = json.load(f)
                x, y = int(data["x"]), int(data["y"])
                # only restore if still on a visible screen
                screen = QApplication.primaryScreen().availableGeometry()
                if -WIDGET_SIZE < x < screen.right() and -WIDGET_SIZE < y < screen.bottom():
                    return (x, y)
        except Exception:
            print("[Kogane] Could not read saved position:")
            traceback.print_exc()
        return None

    def _save_position(self):
        try:
            with open(POS_FILE, "w") as f:
                json.dump({"x": self.x(), "y": self.y()}, f)
            print(f"[Kogane] Position saved ({self.x()}, {self.y()})")
        except Exception:
            print("[Kogane] Could not save position:")
            traceback.print_exc()

    # ---------------------------------------------------------------- input
    # Left-press then move  -> drag the icon anywhere on screen
    # Left-press then release (no move) -> counts as a click
    # Right-click -> dismiss
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPos()
            self._press_widget_pos = self.pos()
            self._dragging = False
        elif event.button() == Qt.RightButton:
            self.dismiss()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        delta = event.globalPos() - self._press_global
        if not self._dragging and delta.manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
        if self._dragging:
            self.move(self._press_widget_pos + delta)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.OpenHandCursor)
            self._save_position()
            self.moved.emit(self.x(), self.y())
        else:
            self.clicked.emit()


# --------------------------------------------------------------------------
# Standalone demo — run `python kogane_animation.py` to test the animation
# --------------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    icon = KoganeIconWidget("kogane.png")
    icon.place_bottom_right()
    icon.summon()
    # clicking the icon replays the summon animation in this demo
    icon.clicked.connect(icon.summon)
    icon.dismissed.connect(app.quit)
    print("[Kogane] Demo running — left-click icon to replay, right-click to dismiss")
    sys.exit(app.exec_())
