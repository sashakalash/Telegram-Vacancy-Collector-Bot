import os
from dotenv import load_dotenv

load_dotenv()

# --- Telethon (personal account) ---
TG_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TG_API_HASH = os.getenv("TELEGRAM_API_HASH")

# --- Telegram Bot ---
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MY_CHAT_ID = int(os.getenv("TELEGRAM_CHAT_ID"))

# --- Google Sheets ---
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
SHEET_NAME = os.getenv("Collector", "dedup_log")
