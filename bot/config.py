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
    target_channel_id: str
    telegram_api_id: int
    telegram_api_hash: str
    telegram_phone: str
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

        return cls(
            bot_token=_require("BOT_TOKEN"),
            moderation_chat_id=int(_require("MODERATION_CHAT_ID")),
            target_channel_id=_require("TARGET_CHANNEL_ID"),
            telegram_api_id=int(_require("TELEGRAM_API_ID")),
            telegram_api_hash=_require("TELEGRAM_API_HASH"),
            telegram_phone=_require("TELEGRAM_PHONE"),
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
            db_path=BASE_DIR / "data" / "bot.sqlite3",
        )


settings = Settings.load()
