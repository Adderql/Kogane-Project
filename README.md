# Kogane — AI Desktop Assistant

> A floating AI-powered desktop assistant for Windows, built in Python. Summon it with Ctrl+Space, ask anything, get real-time answers — without leaving your screen.

<video src="https://github.com/user-attachments/assets/3e048eba-ebef-4838-8cf6-2bbdd49c322d" controls width="100%"></video>

---

## What it does

Kogane sits on your desktop as a floating animated window, summoned with Ctrl+Space. It connects to a large language model via the Groq API and acts on your machine through natural language — opening apps, reading your screen, answering from the web with sources, controlling media, remembering facts, and setting reminders.

**Shipped and running:**
- Floating always-on-top window with cursor-following animated eyes
- Real-time AI responses via Groq tool calling + shikigami persona
- Screen reading — region snip sent to vision model for context-aware answers
- Web answers with cited sources
- App launcher, media controls, clipboard access
- Reminder system with per-turn deduplication
- SQLite memory — conversation history, permanent facts, AI-generated titles
- Email composition (mailto + Gmail fallback)
- Calendar event creation (Outlook COM, .ics fallback)
- Stealth mode — automatically parks when fullscreen apps (e.g. games) are detected
- Native Windows hotkey (RegisterHotKey — no keyboard hook)
- Document creation (.docx / .txt via python-docx)

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python |
| GUI Framework | PyQt5 |
| AI Chat Model | openai/gpt-oss-120b (via Groq) |
| Vision Model | Llama-4 Scout (via Groq) |
| Voice (planned) | Whisper Turbo (via Groq) |
| Storage | SQLite |
| OS Integrations | Win32 API, Outlook COM, SMTP, python-docx |

---

## Getting started

### Prerequisites
- Python 3.10+
- A free Groq API key — sign up at [console.groq.com](https://console.groq.com), it's free and takes 2 minutes. No credit card required.

### Installation

```bash
# 1. Clone the repo
git clone https://github.com/Adderql/Kogane-Project.git
cd Kogane-Project

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file
echo GROQ_API_KEY=your_key_here > .env

# 4. Run Kogane
python kogane.py
```

---

## Project structure

```
Kogane-Project/
├── kogane.py              # Main entry point
├── kogane_animation.py    # Character animation engine
├── requirements.txt
├── .env                   # Your API key (not committed)
└── .gitignore
```

---

## Roadmap

### In progress
- **System alerts** — winotify toasts + launch-on-startup so reminders fire as true machine-level alarms even when Kogane is closed
- **Email & calendar polish** — full SMTP path and Outlook COM zero-click event creation
- **Document generation** — real .docx/.txt output via python-docx
- **Response speed & accuracy** — ongoing tuning of tool call routing, prompt structure, and model parameters to reduce latency and improve how reliably the right tool fires for a given request

### Planned
- **Voice input** — Whisper Turbo hold-to-talk, transcript piped directly into the input bar
- **Routines** — named app sets ("start work" opens VS Code + Chrome + Spotify in one command)
- **Daily briefing** — "start my day" surfaces pending reminders, calendar events, and a weather/news summary
- **Task tracking** — add / list / complete tasks from natural language
- **Browser agent** — scoped web automation via open-source browser-use (forms, comparisons, multi-site lookups), sandboxed to the browser
- **CUA prototype** — pyautogui + vision screenshot-action loop inside a VMware sandbox (portfolio experiment only)

---

## Engineering notes

Kogane is on its 7th major revision, started on tkinter and migrated to PyQt5. Real obstacles solved along the way include:

- **Blank responses until click** — traced to a nested `QGraphicsOpacityEffect` on the panel level conflicting with per-bubble effects; removed and replaced with `windowOpacity`
- **Model fabricating actions** — tool results reworded to be un-paraphrasable; output sanitizer strips fabricated action text
- **Duplicate tool calls** — within-turn dedupe + DB-level reminder dedupe + per-turn caps on search tools
- **Gaming lag spikes** — switched to native `RegisterHotKey` (no keyboard hook), added fullscreen stealth mode and 30fps idle animation
- **Font never applying** — load order fix (fonts loaded before `app.setFont`) + correct Google Fonts naming convention

---

*David Egbuna · [github.com/Adderql](https://github.com/Adderql) · [linkedin.com/in/david-egbuna](https://linkedin.com/in/david-egbuna)*
