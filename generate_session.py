Claude Code: Open in Primary Editorfrom telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = 38640576
API_HASH = "57b42c2921c77aebeb9e8b716f955546"

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print("\nВаша SESSION_STRING:\n")
    print(client.session.save())