# Telegram Vacancies Collector

Monitors Telegram channels and company career pages for job postings matching your keywords. Filters noise via exclude keywords, writes matches to Google Sheets, and sends a Telegram notification. Channels, career pages and keywords are managed in Google Sheets — no code changes needed. Keywords and channels are hot-reloaded every 30 minutes; career pages are checked once a day.

## Project Structure

```
├── main.py           # Entry point, Telethon listener
├── config.py         # Env var bindings
├── filter.py         # Keyword filtering logic
├── sheets.py         # Google Sheets read/write
├── notifier.py       # Telegram bot notifications
├── state.py          # What has been seen, saved to STATE_FILE
├── career_sources.py # Reads jobs from career links
├── career_scanner.py # Daily career page check
├── tests/            # Run with: python -m unittest discover -s tests -t .
├── Procfile          # Railway worker process
├── requirements.txt
├── .env              # Secrets — do not commit
└── credentials.json  # Google Service Account — do not commit
```

## Google Sheets Structure

- Sheet `channels` — columns: `handle`, `channel_id`
- Sheet `keywords` — columns: `keyword`, `type` (`include` / `exclude`)

- Sheet `career_pages` — paste career links into column `url`, from row 2. The app fills in `status`, `jobs` and `last_checked`
- Sheet `locations` — column `word`, the places a job's location must mention

The app creates `career_pages` and `locations` the first time it runs.

Edit the sheet; keyword and channel changes are picked up automatically within 30 minutes (no restart needed). Career links and location words are read at each daily check.

## Career Pages

Once a day the app reads every link in `career_pages`:

- **Job platforms** (Greenhouse, Lever, Ashby, Workable, Gem, Rippling, BambooHR, Workday, Teamtailor, Recruitee, Zoho Recruit) are read through their job feed, detected from the link or the company's page. Feeds return all of a company's jobs and ignore filters saved in the link.
- **Other pages** are read for links that look like jobs. They use the saved link as is, and may break if the site is redesigned. Pages that need a browser or block the app show as `No jobs found` or `Can't read`.

The first read of a link stays quiet and only remembers the jobs already there. After that, each new job goes through these filters:

1. **Location:** must mention a word from `locations`, or be plain "Remote". "Remote - Poland" is cut. Jobs with no location are kept.
2. **Include keywords:** checked against the title and full description.
3. **Exclude keywords:** checked against the title only, because long descriptions mention everything.

Matches go to the same results sheet and Telegram chat as channel posts. You also get a Telegram message when a link that was working stops working or suddenly shows no jobs.

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` | Telethon app ID (from my.telegram.org) |
| `TELEGRAM_API_HASH` | Telethon app hash |
| `TELEGRAM_BOT_TOKEN` | Bot token for notifications (from @BotFather) |
| `TELEGRAM_CHAT_ID` | Your personal chat ID — where notifications are sent |
| `SESSION_STRING` | Base64 Telethon session string (see below) |
| `GOOGLE_CREDENTIALS_FILE` | Path to service account JSON (default: `credentials.json`) |
| `GOOGLE_SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `Collector` | Sheet tab name for dedup log (default: `dedup_log`) |
| `STATE_FILE` | Where seen messages and jobs are saved. On Railway, point it at a volume (default: `state.json`) |
| `CAREER_SCAN_INTERVAL_HOURS` | Hours between career page checks (default: `24`) |

## Railway Deployment

The bot runs as a Railway **worker** (persistent process, no HTTP port).

### 1. Generate SESSION_STRING (once, locally)

Railway has no interactive terminal for first auth, so generate the session string locally first:

```bash
python3 -m venv venv && source venv/bin/activate
pip install telethon python-dotenv
python3 - <<'EOF'
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
import os, getpass

api_id = int(input("API_ID: "))
api_hash = input("API_HASH: ")

with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nSESSION_STRING =", client.session.save())
EOF
```

Copy the printed string and set it as `SESSION_STRING` in Railway environment variables.

### 2. Deploy

```bash
# Push to the repo connected to Railway — deploy triggers automatically
git push origin main
```

Railway reads `Procfile` and runs `worker: python main.py` as a persistent background process.

### 3. Logs

In the Railway dashboard → your service → **Logs** tab.

Or via CLI:

```bash
railway logs
```

## Local Development

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values
python main.py
```

On first run without `SESSION_STRING`, Telethon will prompt for your phone number and auth code and save `monitor_session.session` locally.
