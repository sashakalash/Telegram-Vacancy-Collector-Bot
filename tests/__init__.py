import os

# config.py requires these at import time; dummies keep tests away from real accounts.
os.environ["TELEGRAM_API_ID"] = "1"
os.environ["TELEGRAM_API_HASH"] = "test"
os.environ["TELEGRAM_BOT_TOKEN"] = "1:test"
os.environ["TELEGRAM_CHAT_ID"] = "1"
os.environ["GOOGLE_SPREADSHEET_ID"] = "test"
