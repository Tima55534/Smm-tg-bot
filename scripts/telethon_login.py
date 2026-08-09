"""One-time interactive login for the Telethon userbot session.

The bot needs to READ public Telegram channels it doesn't own (soliqnews,
uz_buxgalter, bank_kuni), which the Bot API cannot do. Telethon logs in as a
regular Telegram user account instead, using the phone number in .env.

Run this manually once, from a terminal you can type into:

    python scripts/telethon_login.py

It will ask for the login code sent to TELEGRAM_PHONE (and a 2FA password if
you have one enabled). After it succeeds, a session file is saved to
data/telethon_userbot.session and the bot can read channels without asking
again.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.sources.telegram_channels import SESSION_PATH  # noqa: E402


async def main() -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), settings.telegram_api_id, settings.telegram_api_hash)
    await client.start(phone=settings.telegram_phone)
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (id={me.id}). Session saved to {SESSION_PATH}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
