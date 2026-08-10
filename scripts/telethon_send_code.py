"""Step 1 of a non-interactive Telethon login: request the login code.

Unlike telethon_login.py (which blocks on input() for the code), this script
just sends the code to the phone/Telegram app and exits. Pair with
telethon_confirm_code.py once you have the code in hand.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.sources.telegram_channels import SESSION_PATH  # noqa: E402

STATE_PATH = SESSION_PATH.parent / "telethon_login_state.json"


async def main() -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(SESSION_PATH), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()

    if await client.is_user_authorized():
        print("ALREADY_AUTHORIZED")
        await client.disconnect()
        return

    result = await client.send_code_request(settings.telegram_phone)
    STATE_PATH.write_text(json.dumps({"phone_code_hash": result.phone_code_hash}))
    print("CODE_SENT")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
