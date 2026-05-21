import asyncio
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession

import config
from filter import matches, matched_keywords
from notifier import send_notification
from sheets import load_channels, load_keywords, write_row
from state import get_last_seen, mark_seen, mark_written, was_written

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def build_link(channel: str, message_id: int) -> str:
    return f"https://t.me/{channel}/{message_id}"


KEYWORDS_RELOAD_INTERVAL = 1800  # seconds
BACKFILL_LIMIT_PER_CHANNEL = 200  # cap iter_messages on cold start


async def process_message(message, chat, kw_state: dict) -> None:
    """Match → dedup → write+notify. Shared by live, edit, and backfill paths."""
    text = message.text or message.caption or ""
    channel = chat.username or str(chat.id)

    if not matches(text, kw_state["include"], kw_state["exclude"]):
        return

    if was_written(channel, message.id):
        logger.info(f"Skip duplicate in @{channel}: msg_id={message.id}")
        return

    keywords = matched_keywords(text, kw_state["include"])
    link = build_link(channel, message.id)

    logger.info(f"Match in @{channel} (msg {message.id}): {keywords}")

    results = await asyncio.gather(
        asyncio.to_thread(write_row, channel, keywords, text, link),
        send_notification(channel, keywords, text, link),
        return_exceptions=True,
    )
    write_ok = results[0] is True

    if write_ok:
        mark_written(channel, message.id)
    else:
        logger.error(
            f"Sheet write FAILED for @{channel} msg {message.id} — "
            f"will retry on next edit/restart (result={results[0]!r})"
        )


async def backfill_channel(client: TelegramClient, channel: str, kw_state: dict) -> int:
    """Fetch messages newer than last_seen_id and run them through process_message."""
    last_id = get_last_seen(channel)
    # iter_messages defaults to newest-first; collect then process oldest-first
    # so sheet rows stay in chronological order.
    fetched = []
    async for msg in client.iter_messages(
        channel, min_id=last_id, limit=BACKFILL_LIMIT_PER_CHANNEL
    ):
        fetched.append(msg)

    if not fetched:
        return 0

    fetched.reverse()  # oldest first
    try:
        chat = await client.get_entity(channel)
    except Exception as e:
        logger.error(f"Backfill @{channel}: cannot resolve entity: {e}")
        return 0

    processed = 0
    for msg in fetched:
        try:
            await process_message(msg, chat, kw_state)
            mark_seen(channel, msg.id)
            processed += 1
        except Exception as e:
            logger.error(f"Backfill @{channel}: error on msg {msg.id}: {e}", exc_info=True)

    return processed


async def main():
    logger.info("Starting monitor...")

    channels = await asyncio.to_thread(load_channels)
    include_kw, exclude_kw = await asyncio.to_thread(load_keywords)

    logger.info(f"Channels: {channels}")
    logger.info(f"Include: {include_kw}")
    logger.info(f"Exclude: {exclude_kw}")

    kw_state = {"include": include_kw, "exclude": exclude_kw}

    session = StringSession(config.SESSION_STRING) if config.SESSION_STRING else "monitor_session"

    client = TelegramClient(
        session,
        config.TG_API_ID,
        config.TG_API_HASH,
        catch_up=True,  # ask Telegram for missed updates after reconnect
    )

    async def on_new_message(event):
        message = event.message
        chat = await event.get_chat()
        channel = chat.username or str(chat.id)
        snippet = (message.text or message.caption or "")[:300]
        logger.info(f"Raw text from @{channel} (msg {message.id}): {snippet}")
        await process_message(message, chat, kw_state)
        mark_seen(channel, message.id)

    async def on_edited_message(event):
        message = event.message
        chat = await event.get_chat()
        channel = chat.username or str(chat.id)
        snippet = (message.text or message.caption or "")[:300]
        logger.info(f"Edited text from @{channel} (msg {message.id}): {snippet}")
        # do NOT mark_seen on edits — message.id may be older than last_seen_id
        await process_message(message, chat, kw_state)

    async def reload_keywords_loop():
        while True:
            await asyncio.sleep(KEYWORDS_RELOAD_INTERVAL)
            try:
                new_include, new_exclude = await asyncio.to_thread(load_keywords)
                kw_state["include"] = new_include
                kw_state["exclude"] = new_exclude
                logger.info(
                    f"Keywords reloaded: include={len(new_include)}, exclude={len(new_exclude)}"
                )
            except Exception as e:
                logger.error(f"Failed to reload keywords: {e}")

    async def reload_channels_loop():
        nonlocal valid_channels, new_handle, edit_handle
        while True:
            await asyncio.sleep(KEYWORDS_RELOAD_INTERVAL)
            try:
                new_channels = await asyncio.to_thread(load_channels)
                validated = []
                for ch in new_channels:
                    try:
                        await client.get_input_entity(ch)
                        validated.append(ch)
                    except ValueError:
                        logger.warning(f"Channel not found on reload, skipping: {ch}")
                if set(validated) != set(valid_channels):
                    valid_channels = validated
                    client.remove_event_handler(new_handle)
                    client.remove_event_handler(edit_handle)
                    new_handle = client.add_event_handler(
                        on_new_message, events.NewMessage(chats=valid_channels)
                    )
                    edit_handle = client.add_event_handler(
                        on_edited_message, events.MessageEdited(chats=valid_channels)
                    )
                    logger.info(f"Channels updated: {len(valid_channels)} active")
                else:
                    logger.info("Channels unchanged, no update needed")
            except Exception as e:
                logger.error(f"Failed to reload channels: {e}")

    await client.start()

    # Validate channels — skip ones that don't exist
    valid_channels = []
    for ch in channels:
        try:
            await client.get_input_entity(ch)
            valid_channels.append(ch)
        except ValueError:
            logger.warning(f"Channel not found, skipping: {ch}")

    new_handle = client.add_event_handler(
        on_new_message, events.NewMessage(chats=valid_channels)
    )
    edit_handle = client.add_event_handler(
        on_edited_message, events.MessageEdited(chats=valid_channels)
    )

    logger.info(f"Monitoring {len(valid_channels)}/{len(channels)} channels")

    # Cold-start backfill: anything posted while we were down (capped per channel).
    logger.info("Running startup backfill...")
    total = 0
    for ch in valid_channels:
        try:
            n = await backfill_channel(client, ch, kw_state)
            if n:
                logger.info(f"Backfill @{ch}: processed {n} messages")
            total += n
        except Exception as e:
            logger.error(f"Backfill failed for @{ch}: {e}", exc_info=True)
    logger.info(f"Backfill complete: {total} messages processed")

    logger.info("Telethon connected. Waiting for messages...")
    asyncio.create_task(reload_keywords_loop())
    asyncio.create_task(reload_channels_loop())
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
