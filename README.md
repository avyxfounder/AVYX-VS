# AVYX VS

Telegram media conversion bot by AVYX.

Features:
- Video -> Telegram video note (circle)
- Image -> short Telegram video note
- Audio/music -> Telegram voice message
- Video with audio -> Telegram voice message
- Audio/video sent as a document
- FFmpeg processing
- Temporary files are deleted after every job
- Docker support

## Run on a Linux VPS

1. Install Docker and Docker Compose.
2. Clone this repository.
3. Copy `.env.example` to `.env`.
4. Put your BotFather token into `BOT_TOKEN`.
5. Run `docker compose up -d --build`.

## Local run

Requirements: Python 3.11+ and FFmpeg/FFprobe.

Copy `.env.example` to `.env`, set `BOT_TOKEN`, then run:

    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    python -m bot

## Important

The standard Telegram Bot API has download limits for normal bots. This first version is configured conservatively for files up to 20 MB. When we deploy to a VPS, we can add Telegram Local Bot API Server for much larger media.

No webhook or public domain is required for the first deployment: the bot uses long polling.

## Security

Never commit `.env` or a real bot token. `.gitignore` already excludes `.env`.

Architecture:

GitHub -> Linux VPS -> AVYX VS -> Telegram

Recommended next deployment targets: Oracle Cloud, WispByte, or another Linux VPS.