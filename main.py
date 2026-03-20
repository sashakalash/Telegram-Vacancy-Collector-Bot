import asyncio
import logging

from telethon import TelegramClient, events

import config
from filter import matches, matched_keywords
from notifier import send_notification
from sheets import load_channels, load_keywords, write_row

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

def build_link(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}"


async def main():
    logger.info("Starting monitor...")

    channels = await asyncio.to_thread(load_channels)
    include_kw, exclude_kw = await asyncio.to_thread(load_keywords)

    logger.info(f"Channels: {channels}")
    logger.info(f"Include: {include_kw}")
    logger.info(f"Exclude: {exclude_kw}")

    client = TelegramClient(
        "monitor_session",
        config.TG_API_ID,
        config.TG_API_HASH,
    )

    @client.on(events.NewMessage(chats=channels))
    async def handler(event):
        message = event.message
        text = message.text or message.caption or ""

        if not matches(text, include_kw, exclude_kw):
            return

        chat = await event.get_chat()
        channel = chat.username or str(chat.id)

        keywords = matched_keywords(text, include_kw)
        link = build_link(channel, message.id)

        logger.info(f"Match in @{channel}: {keywords}")

        await asyncio.gather(
            asyncio.to_thread(write_row, channel, keywords, text, link),
            send_notification(channel, keywords, text, link),
        )

    await client.start()

    # Validate channels — skip ones that don't exist
    valid_channels = []
    for ch in channels:
        try:
            await client.get_input_entity(ch)
            valid_channels.append(ch)
        except ValueError:
            logger.warning(f"Channel not found, skipping: {ch}")

    client.remove_event_handler(handler)
    client.add_event_handler(handler, events.NewMessage(chats=valid_channels))

    logger.info(f"Monitoring {len(valid_channels)}/{len(channels)} channels")
    logger.info("Telethon connected. Waiting for messages...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
