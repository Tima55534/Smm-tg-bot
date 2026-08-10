"""Step 2 of a non-interactive Telethon login: submit the code (and, if
needed, the 2FA password) that was sent by telethon_send_code.py.

Usage:
    python scripts/telethon_confirm_code.py <code> [2fa_password]
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402

from bot.config import settings  # noqa: E402
from bot.sources.telegram_channels import SESSION_PATH  # noqa: E402

STATE_PATH = SESSION_PATH.parent / "telethon_login_state.json"


async def main() -> None:
    if len(sys.argv) < 2:
        print("USAGE: python scripts/telethon_confirm_code.py <code> [2fa_password]")
        return

    code = sys.argv[1]
    password = sys.argv[2] if len(sys.argv) > 2 else None

    state = json.loads(STATE_PATH.read_text())
    client = TelegramClient(str(SESSION_PATH), settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()

    try:
        await client.sign_in(
            phone=settings.telegram_phone,
            code=code,
            phone_code_hash=state["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        if not password:
            print("NEED_PASSWORD")
            await client.disconnect()
            return
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"LOGGED_IN as {me.first_name} (id={me.id})")
    await client.disconnect()

    session_file = Path(f"{SESSION_PATH}.session")
    b64_path = SESSION_PATH.parent / "telethon_session_base64.txt"
    b64_path.write_text(base64.b64encode(session_file.read_bytes()).decode("ascii"))
    print(f"Session saved. Base64 copy for Railway written to: {b64_path}")

    STATE_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
