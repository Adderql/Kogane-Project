# Kogane — AI Desktop Assistant

> A floating AI-powered desktop assistant built in Python. Ask questions, get real-time answers — without leaving your screen.

<!-- Replace the line below with your actual GIF once you have it -->
![Kogane Demo](demo.gif)

---

## What it does

Kogane sits on your desktop as a floating window and connects to a large language model via the Groq API to answer questions in real time. It was built as a personal productivity and IT support tool — helping users get fast, clear answers without switching away from what they're working on.

**Key features:**
- Floating always-on-top window that stays out of your way
- Real-time responses powered by Groq's API
- Custom animated character that reacts to activity
- Stealth mode — automatically parks when fullscreen apps (e.g. games) are detected
- Email and calendar integration (mailto / Outlook COM automation)
- Hotkey support via native Windows RegisterHotKey

---

## Tech stack

| Layer | Technology |
|---|---|
| Language | Python |
| GUI Framework | PyQt5 |
| AI Backend | Groq API |
| Model | openai/gpt-oss-120b (via Groq) |
| Tools / Integrations | Win32 API, Outlook COM, SMTP |

---

## Getting started

### Prerequisites
- Python 3.10+
- A free [Groq API key](https://console.groq.com)

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

## About

Built independently across 5+ development cycles, refining prompt engineering, API tool calling, GUI architecture, and error handling. Kogane is an ongoing project — current roadmap includes Whisper Turbo voice input and an expanded README with full demo.

---

*David Egbuna · [github.com/Adderql](https://github.com/Adderql) · [linkedin.com/in/david-egbuna](https://linkedin.com/in/david-egbuna)*
