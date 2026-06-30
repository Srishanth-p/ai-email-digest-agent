# Email Agent — AI-Driven Email Digest

An AI-powered email automation agent that fetches your unread emails twice a day, summarises and categorises each one using an LLM, and delivers a consolidated digest straight to your phone via Telegram or Discord.

---

## Features

| Feature | Details |
|---|---|
| **Email fetching** | IMAP over SSL (Gmail App Password or any IMAP server) |
| **AI processing** | Single LLM call per email handles both categorization + summarization |
| **LLM backends** | Ollama (local, offline) · Gemini 2.0 Flash (free API) · Groq/Llama-3 (free API) |
| **Notification** | Telegram Bot API **or** Discord Webhook |
| **Scheduling** | APScheduler — runs at 8 AM & 8 PM (configurable) |
| **Deduplication** | Marks emails as read + applies custom Gmail label after processing |
| **100% free** | All three LLM options are completely free — no billing required |

---

## Project Structure

```
Email Agent/
├── agent.py            # Main entry point + scheduler
├── config.py           # Centralised config (reads from .env)
├── email_fetcher.py    # IMAP email fetching + marking
├── llm_processor.py    # AI summarization & categorization
├── notifier.py         # Telegram / Discord digest sender
├── .env                # Your secrets (never commit this)
├── .env.example        # Template to copy from
├── requirements.txt    # Python dependencies
├── agent.log           # Auto-created log file at runtime
└── README.md
```

---

## Quick Start

### 1 — Clone / download and set up a virtual environment

```bash
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### 3 — Create your `.env` file

```bash
cp .env.example .env
```

Then open `.env` in any text editor and fill in your credentials (see configuration guide below).

### 4 — Test immediately

```bash
python agent.py --run-now
```

This runs the full pipeline once and sends you a test digest.

### 5 — Start the scheduler (runs in the background)

```bash
python agent.py
```

The agent will wait silently until 8:00 AM or 8:00 PM and then execute.

---

## Configuration Guide

All settings live in your `.env` file. Here is what each section requires.

---

### Email Access (Gmail — Recommended)

Gmail blocks plain passwords. You need an **App Password**.

1. Enable 2-Step Verification on your Google Account:  
   https://myaccount.google.com/security

2. Create an App Password:  
   https://myaccount.google.com/apppasswords  
   Select **Mail** + **Windows Computer** (or any device). Copy the 16-character password.

3. Set in `.env`:
```env
EMAIL_PROVIDER=gmail
EMAIL_ADDRESS=you@gmail.com
EMAIL_APP_PASSWORD=abcd efgh ijkl mnop
```

> **IMAP must be enabled in Gmail:**  
> Gmail Settings → See all settings → Forwarding and POP/IMAP → Enable IMAP

---

### Email Access (Generic IMAP)

```env
EMAIL_PROVIDER=imap
EMAIL_ADDRESS=you@yourdomain.com
EMAIL_APP_PASSWORD=your_imap_password
IMAP_HOST=mail.yourdomain.com
IMAP_PORT=993
```

---

### LLM — Option A: Ollama (Local, 100% Free, Recommended)

Runs entirely on your own machine. No internet connection, no account, no usage limits.

1. Install Ollama: https://ollama.com
2. Pull a model: `ollama pull llama3`
3. Set in `.env`:
```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

---

### LLM — Option B: Google Gemini (Free Cloud API)

Free tier: 15 RPM · 1,500 requests/day · 1M tokens/day. No billing required.

1. Get a free API key at: https://aistudio.google.com/apikey
2. Set in `.env`:
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
```

---

### LLM — Option C: Groq Cloud (Free Cloud API)

Free tier: 14,400 requests/day on Llama-3. No billing required.

1. Get a free API key at: https://console.groq.com
2. Set in `.env`:
```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama3-8b-8192
```

---

### Notifications — Telegram (Recommended)

**Step 1 — Create a bot:**
1. Open Telegram and search for `@BotFather`
2. Send `/newbot` and follow the prompts
3. Copy the **Bot Token** (format: `123456789:AABBCCDDEEFFaabbccddeeff`)

**Step 2 — Get your Chat ID:**
1. Send any message to your new bot
2. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Look for `"chat":{"id": 987654321 ...}` — that number is your Chat ID

**Step 3 — Set in `.env`:**
```env
NOTIFICATION_PROVIDER=telegram
TELEGRAM_BOT_TOKEN=123456789:AABBCCDDEEFFaabbccddeeff
TELEGRAM_CHAT_ID=987654321
```

---

### Notifications — Discord

1. In your Discord server: **Server Settings → Integrations → Webhooks → New Webhook**
2. Copy the webhook URL
3. Set in `.env`:
```env
NOTIFICATION_PROVIDER=discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

---

### Schedule & Timezone

```env
SCHEDULE_TIMES=08:00,20:00
TIMEZONE=Asia/Kolkata
```

Find your timezone name at: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones  
(e.g. `America/New_York`, `Europe/London`, `Asia/Singapore`)

---

## Sample Digest

```
Morning Email Digest (08:00 AM)
────────────────────────────────

4 new email(s) processed

Campus Placements & Career
  - Google Recruiting | Interview Update
    Technical round scheduled for Friday at 3 PM – action required.

Newsletters & Tech Digests
  - TLDR Tech | AI Weekly #142
    Roundup of new open-source LLM releases and framework updates.

Advertisements & Marketing
  - 2 promotional emails omitted.

────────────────────────────────
Sent by Email Agent
```

---

## Running as a Background Service

### Windows — Task Scheduler

1. Open **Task Scheduler** → Create Basic Task
2. Trigger: **At log on** (or Daily)
3. Action: `Start a program`
   - Program: `C:\path\to\.venv\Scripts\python.exe`
   - Arguments: `agent.py`
   - Start in: `C:\path\to\Email Agent`

### macOS / Linux — systemd service

Create `/etc/systemd/system/email-agent.service`:

```ini
[Unit]
Description=AI Email Agent
After=network.target

[Service]
WorkingDirectory=/path/to/Email Agent
ExecStart=/path/to/.venv/bin/python agent.py
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable email-agent
sudo systemctl start email-agent
sudo systemctl status email-agent
```

### macOS — launchd (simpler alternative)

```bash
# Keep running in a terminal session with auto-restart:
while true; do python agent.py; sleep 5; done
```

---

## Security Notes

| Concern | Mitigation |
|---|---|
| Credential exposure | All secrets in `.env`, never hardcoded |
| `.env` in version control | Add `.env` to `.gitignore` |
| Email password safety | Use App Passwords, not your main account password |
| API key exposure | Rotate keys if the repository is accidentally made public |
| Network failures | 3-retry exponential back-off on all external calls |

Add to `.gitignore`:
```
.env
agent.log
__pycache__/
.venv/
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `EnvironmentError: EMAIL_ADDRESS not set` | Copy `.env.example` to `.env` and fill it in |
| Gmail IMAP login failed | Enable IMAP in Gmail settings; use an App Password, not your main password |
| `No module named 'openai'` | Run `pip install -r requirements.txt` |
| Telegram: `401 Unauthorized` | Double-check `TELEGRAM_BOT_TOKEN` |
| Telegram: `400 Bad Request chat not found` | Ensure you have sent a message to the bot first |
| No emails fetched | Check that `LOOKBACK_HOURS` covers the right window; emails must be unread |
| LLM returns non-JSON | Temporary model glitch — retried automatically up to 3 times |

Check `agent.log` for detailed timestamped output for every run.

---

## Dependencies

| Package | Purpose |
|---|---|
| `python-dotenv` | Load `.env` into environment |
| `openai` | Ollama + Groq OpenAI-compatible client (no OpenAI account needed) |
| `APScheduler` | Cron-style job scheduler |
| `requests` | HTTP calls for Telegram / Discord |
| `beautifulsoup4` + `lxml` | Strip HTML from email bodies |
| `pytz` | Timezone-aware datetime handling |

---

*Built with Python · Runs locally · No server required*
