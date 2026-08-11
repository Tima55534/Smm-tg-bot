from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass
class WebSource:
    name: str
    type: str
    options: dict = field(default_factory=dict)


@dataclass
class Settings:
    bot_token: str
    moderation_chat_id: int
    target_channel_ids: list[str]
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
    telethon_session_string: str | None
    anthropic_api_key: str
    openai_api_key: str

    interval_days: int
    schedule_time: str
    timezone: str
    poll_every_n_posts: int
    max_items_per_source: int

    web_sources: list[WebSource]
    telegram_channels: list[str]

    text_model: str
    image_model: str
    image_size: str
    post_style: str
    image_style: str

    db_path: Path

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        config_path = config_path or (BASE_DIR / "config.yaml")
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        web_sources = []
        for item in raw["sources"]["web"]:
            item = dict(item)
            name = item.pop("name")
            type_ = item.pop("type")
            web_sources.append(WebSource(name=name, type=type_, options=item))

        # TARGET_CHANNEL_ID accepts a comma-separated list; TARGET_CHANNEL_ID2,
        # TARGET_CHANNEL_ID3, ... are also picked up as additional channels,
        # for platforms like Railway where separate named variables are more
        # natural to add than editing one into a comma-joined value.
        target_channel_ids = [
            c.strip() for c in _require("TARGET_CHANNEL_ID").split(",") if c.strip()
        ]
        n = 2
        while True:
            extra = os.environ.get(f"TARGET_CHANNEL_ID{n}")
            if not extra:
                break
            target_channel_ids += [c.strip() for c in extra.split(",") if c.strip()]
            n += 1

        return cls(
            bot_token=_require("BOT_TOKEN"),
            moderation_chat_id=int(_require("MODERATION_CHAT_ID")),
            target_channel_ids=target_channel_ids,
            telegram_api_id=int(_require("TELEGRAM_API_ID")),
            telegram_api_hash=_require("TELEGRAM_API_HASH"),
            telegram_phone=_require("TELEGRAM_PHONE"),
            telethon_session_string=os.environ.get("TELETHON_SESSION_STRING") or None,
            anthropic_api_key=_require("ANTHROPIC_API_KEY"),
            openai_api_key=_require("OPENAI_API_KEY"),
            interval_days=int(raw["schedule"]["interval_days"]),
            schedule_time=str(raw["schedule"]["time"]),
            timezone=str(raw["schedule"]["timezone"]),
            poll_every_n_posts=int(raw["poll_every_n_posts"]),
            max_items_per_source=int(raw["max_items_per_source"]),
            web_sources=web_sources,
            telegram_channels=list(raw["sources"]["telegram"]),
            text_model=raw["ai"]["text_model"],
            image_model=raw["ai"]["image_model"],
            image_size=raw["ai"]["image_size"],
            post_style=raw["ai"]["post_style"],
            image_style=raw["ai"]["image_style"],
            db_path=BASE_DIR / "data" / "bot.sqlite3",
        )


settings = Settings.load()
