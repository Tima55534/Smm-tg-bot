from __future__ import annotations

import base64
import logging
from pathlib import Path

from telethon import TelegramClient

from .base import NewsItem

SESSION_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "telethon_userbot"

logger = logging.getLogger(__name__)


def ensure_session_from_env(session_b64: str | None) -> None:
    """Restore the .session file from TELETHON_SESSION_B64 if it isn't already
    on disk. Lets a host that can't run scripts/telethon_login.py interactively
    (e.g. a fresh Railway deploy with no persistent volume) reuse a session
    that was generated elsewhere."""
    session_file = Path(f"{SESSION_PATH}.session")
    if session_file.exists() or not session_b64:
        return
    session_file.parent.mkdir(parents=True, exist_ok=True)
    session_file.write_bytes(base64.b64decode(session_b64))
    logger.info("Restored Telethon session from TELETHON_SESSION_B64")


async def fetch_channel(
    client: TelegramClient, channel_username: str, limit: int = 5
) -> list[NewsItem]:
    items: list[NewsItem] = []
    async for message in client.iter_messages(channel_username, limit=limit):
        if not message.text:
            continue
        items.append(
            NewsItem(
                source=f"tg:{channel_username}",
                external_id=str(message.id),
                title=message.text.split("\n", 1)[0][:120],
                text=message.text,
                url=f"https://t.me/{channel_username}/{message.id}",
                published_at=message.date.timestamp() if message.date else None,
            )
        )
    return items


async def fetch_all(
    api_id: int, api_hash: str, channels: list[str], limit: int = 5
) -> list[NewsItem]:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telethon session not authorized. Run scripts/telethon_login.py once "
            "interactively to log in before starting the bot."
        )

    all_items: list[NewsItem] = []
    try:
        for channel in channels:
            all_items.extend(await fetch_channel(client, channel, limit=limit))
    finally:
        await client.disconnect()

    return all_items
