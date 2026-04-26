# OSCS & Frens Archive

Automated YouTube Shorts bot for the OSCS streamer group and friends.

Pulls top Twitch clips → Discord review → YouTube Shorts, on autopilot.

---

## How it works

```
Twitch clips → Discord review → Queue → Whisper → Gemini title → ffmpeg overlay → YouTube Shorts
```

1. **Fetch** — APScheduler pulls top clips from tracked streamers at noon and midnight
2. **Review** — Discord bot posts clips to #clip-review as embeds
3. **Approve** — React ✅ to approve, ❌ to reject, or reply to set a custom title
4. **Queue** — Approved clips get downloaded, transcribed, titled, and overlaid every 30 minutes
5. **Upload** — Oldest queued clip uploads to YouTube Shorts automatically

---

## Stack

| Component | Tool |
|-----------|------|
| Clip source | Twitch API |
| Review | Discord bot |
| Transcription | OpenAI Whisper (local) |
| Title generation | Gemini 2.0 Flash |
| Overlay | ffmpeg drawtext |
| Upload | YouTube Data API v3 |
| Scheduler | APScheduler |
| Database | SQLite |

---

## Streamers tracked

**OSCS core:** youngbasedgo, yugi2x, redify, bigmonraph, sunnys, santipulgaz, arky, Nosiiree, 1jdab1

**Friends:** bonnie, aozami

---

## Setup

### 1. Clone and create virtual environment
```bash
git clone https://github.com/izzylinjo/oscs-frens-archive.git
cd oscs-frens-archive
python -m venv oscsprojvenv
oscsprojvenv\Scripts\activate
```

### 2. Install dependencies
```bash
pip install python-dotenv requests discord.py openai-whisper apscheduler \
            google-api-python-client google-auth-oauthlib google-auth-httplib2 yt-dlp
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

> ffmpeg must also be installed as a system binary and available in PATH.

### 3. Create `.env`
```
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
GEMINI_API_KEY=
DISCORD_BOT_TOKEN=
DISCORD_USER_ID=
DISCORD_CLIP_REVIEW_CHANNEL_ID=
DISCORD_CLIP_INBOX_CHANNEL_ID=
```

### 4. Add YouTube credentials
- Create a Google Cloud project → enable YouTube Data API v3
- Create OAuth2 credentials (Desktop app) → download as `client_secrets.json`
- Place `client_secrets.json` in the repo root

### 5. Run
```bash
python main.py
```

First run opens a browser for YouTube OAuth2 consent. Token is cached to `youtube_token.json` — only needed once.

---

## Discord workflow

- Drop a Twitch clip URL into **#clip-inbox** to manually submit a clip
- React **✅** in **#clip-review** to approve, **❌** to reject
- Reply to a clip embed with text to set a custom title and auto-approve

---

## Project structure

```
oscs-frens-archive/
├── main.py              # Entry point — scheduler + Discord bot
├── config.py            # All settings and API keys
├── bot/
│   ├── db.py            # SQLite schema and queries
│   ├── twitch.py        # Clip fetching
│   ├── discord_bot.py   # Review interface
│   ├── titles.py        # Whisper + Gemini title generation
│   ├── overlay.py       # ffmpeg overlay
│   ├── queue.py         # Download → process → queue pipeline
│   └── youtube.py       # YouTube upload
├── db/                  # SQLite database (gitignored)
└── downloads/           # Temp clip storage (gitignored)
```

---

## Clip status lifecycle

```
fetched → approved → queued → uploaded
              ↓
           rejected
```
