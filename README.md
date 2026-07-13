# MoriTrustNet

Clean Telegram bot with admin panel, referral system, and environment-based configuration.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your bot token
python run_bot.py
```

## Features

- Admin panel with user management
- Referral system with invite tracking
- Environment-based configuration (.env)
- SQLite database for persistence
- Modular architecture (config, db, identity, bot_app)

## Configuration

Copy `.env.example` to `.env` and fill in:
- `BOT_TOKEN` — Telegram bot token

## Requirements

- Python 3.8+
- `telebot`, `python-dotenv`
