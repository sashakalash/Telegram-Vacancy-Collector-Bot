# Telegram Channel Monitor

Monitors a list of Telegram channels for job postings matching your keywords. Filters out noise via exclude keywords, writes matches to Google Sheets, and sends a Telegram notification instantly. Channels and keywords are managed in Google Sheets — no code changes needed.

## Project Structure

```
tg_monitor/
├── main.py           # Entry point, Telethon listener
├── config.py         # Keys and settings from .env
├── filter.py         # Keyword filtering logic
├── sheets.py         # Google Sheets read/write
├── notifier.py       # Telegram notifications
├── requirements.txt
├── .env              # Secrets (do not commit!)
└── credentials.json  # Google Service Account (do not commit!)
```

## Filters

Channels and keywords are stored in Google Sheets (not in code):

- Sheet `channels` — columns `handle`, `channel_id`
- Sheet `keywords` — columns `keyword`, `type` (`include` / `exclude`)

To add a channel or keyword — edit the sheet and restart the bot.

## Running Locally (Mac)

### 1. Setup (once)

```bash
cd /path/to/project
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Telegram Authorization (once)

```bash
source venv/bin/activate
python main.py
# → enter your phone number and Telegram code
# → monitor_session.session file will be created
# → Ctrl+C after successful connection
```

### 3. Run in Background (survives terminal close)

```bash
source venv/bin/activate
nohup python main.py > monitor.log 2>&1 &
```

### Management

```bash
# Watch logs
tail -f monitor.log

# Stop
pkill -f main.py
```

> The bot will not survive a Mac reboot. For autostart — configure via `launchd`.
