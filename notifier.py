import logging

import telegram

from config import BOT_TOKEN, MY_CHAT_ID

logger = logging.getLogger(__name__)

_bot = None  # cached bot instance


def _get_bot():
    global _bot
    if _bot is None:
        _bot = telegram.Bot(token=BOT_TOKEN)
    return _bot


async def send_notification(
    channel: str, keywords: list[str], text: str, link: str
) -> bool:
    """
    Sends a notification to Telegram.
    Returns True on success, False on error.
    """
    try:
        bot = _get_bot()

        keywords_str = " | ".join(f"#{kw.replace(' ', '_')}" for kw in keywords)
        preview = text[:300] + ("..." if len(text) > 300 else "")

        message = (
            f"🔔 <b>New match</b>\n\n"
            f"📢 <b>Channel:</b> @{channel}\n"
            f"🔑 <b>Keywords:</b> {keywords_str}\n\n"
            f"💬 {preview}\n\n"
            f"🔗 <a href='{link}'>Open message</a>"
        )

        await bot.send_message(
            chat_id=MY_CHAT_ID,
            text=message,
            parse_mode="HTML",
            disable_web_page_preview=False,
        )
        logger.info(f"Notification sent: {channel}")
        return True
    except Exception as e:
        logger.error(f"Error sending notification: {e}")
        return False
