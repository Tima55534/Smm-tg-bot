"""Convert the local file-based Telethon session into a compact StringSession,
suitable for pasting into an env var (TELETHON_SESSION_STRING) on a host that
has no persistent file storage, like Railway.

Run this AFTER a successful login (telethon_login.py, or
telethon_send_code.py + telethon_confirm_code.py):

    python scripts/telethon_export_string_session.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402
from telethon.sessions import StringSession  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.sources.telegram_channels import SESSION_PATH  # noqa: E402


async def main() -> None:
    client = TelegramClient(str(SESSION_PATH), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("NOT_AUTHORIZED - run telethon_login.py first")
        await client.disconnect()
        return

    string_session = StringSession.save(client.session)
    await client.disconnect()

    out_path = SESSION_PATH.parent / "telethon_session_string.txt"
    out_path.write_text(string_session)
    print(f"String session ({len(string_session)} chars) written to: {out_path}")
    print("Copy its contents into TELETHON_SESSION_STRING on your deploy platform.")


if __name__ == "__main__":
    asyncio.run(main())
