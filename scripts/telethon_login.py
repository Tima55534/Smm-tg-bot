"""One-time interactive login for the Telethon userbot session.

The bot needs to READ public Telegram channels it doesn't own (soliqnews,
uz_buxgalter, bank_kuni), which the Bot API cannot do. Telethon logs in as a
regular Telegram user account instead, using the phone number in .env.

Run this manually once, from a terminal you can type into (needs Python +
`pip install -r requirements.txt` first):

    python scripts/telethon_login.py

It will ask for the login code sent to TELEGRAM_PHONE (and a 2FA password if
you have one enabled). After it succeeds:

  - A session file is saved to data/telethon_userbot.session (used if you run
    the bot on this same machine).
  - Its content is also base64-encoded and written to
    data/telethon_session_base64.txt. If the bot runs elsewhere (e.g.
    Railway), open that file, copy its (single-line) contents, and paste them
    into that platform's environment variables as TELETHON_SESSION_B64. The
    bot writes the session file from that variable on first startup — no file
    upload or persistent volume needed.
"""

from __future__ import annotations

import asyncio
import base64
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

    session_file = Path(f"{SESSION_PATH}.session")
    b64_path = SESSION_PATH.parent / "telethon_session_base64.txt"
    b64_path.write_text(base64.b64encode(session_file.read_bytes()).decode("ascii"))
    print(f"\nFor deploying elsewhere (e.g. Railway): copy the contents of")
    print(f"  {b64_path}")
    print("into an env var named TELETHON_SESSION_B64 on that platform.")


if __name__ == "__main__":
    asyncio.run(main())
