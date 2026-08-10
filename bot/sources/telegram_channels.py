from __future__ import annotations

import logging
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

from .base import NewsItem

SESSION_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "telethon_userbot"

logger = logging.getLogger(__name__)

# Skip short channel posts (photo-of-the-day captions, "today is Tuesday"
# calendar reminders, currency-rate one-liners, hashtag-only posts) — there's
# not enough real content in them to rewrite into a substantive post.
MIN_TEXT_LENGTH = 200


def _build_client(api_id: int, api_hash: str, session_string: str | None) -> TelegramClient:
    if session_string:
        # Compact in-memory session restored from TELETHON_SESSION_STRING — no
        # local file needed, so this works on hosts without persistent storage
        # (e.g. a fresh Railway deploy).
        return TelegramClient(StringSession(session_string), api_id, api_hash)

    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(str(SESSION_PATH), api_id, api_hash)


async def fetch_channel(
    client: TelegramClient, channel_username: str, limit: int = 5
) -> list[NewsItem]:
    items: list[NewsItem] = []
    # Scan more than `limit` raw messages since short ones get filtered out.
    async for message in client.iter_messages(channel_username, limit=limit * 4):
        if len(items) >= limit:
            break
        if not message.text or len(message.text) < MIN_TEXT_LENGTH:
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
    api_id: int,
    api_hash: str,
    channels: list[str],
    limit: int = 5,
    session_string: str | None = None,
) -> list[NewsItem]:
    client = _build_client(api_id, api_hash, session_string)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(
            "Telethon session not authorized. Run scripts/telethon_login.py (and "
            "scripts/telethon_export_string_session.py) once to log in before "
            "starting the bot."
        )

    all_items: list[NewsItem] = []
    try:
        for channel in channels:
            all_items.extend(await fetch_channel(client, channel, limit=limit))
    finally:
        await client.disconnect()

    return all_items
