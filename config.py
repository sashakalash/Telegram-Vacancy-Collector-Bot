import os
from dotenv import load_dotenv

load_dotenv()

# --- Telethon (personal account) ---
TG_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TG_API_HASH = os.getenv("TELEGRAM_API_HASH")

# --- Telegram Bot ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

# --- Telethon session (base64-encoded .session file for Railway/cloud deployment) ---
SESSION_STRING = os.getenv("SESSION_STRING")  # If set, used instead of session file

# --- Google Sheets ---
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
SHEET_NAME = os.getenv("Collector", "dedup_log")

# --- Career pages ---
CAREER_SCAN_INTERVAL_HOURS = float(os.getenv("CAREER_SCAN_INTERVAL_HOURS", "24"))
