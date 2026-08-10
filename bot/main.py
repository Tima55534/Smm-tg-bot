from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .ai.image import ImageAI
from .ai.text import TextAI
from .config import BASE_DIR, settings
from .db import Database
from .handlers.admin import build_router as build_admin_router
from .moderation import build_router as build_moderation_router
from .pipeline import Services, start_topic_selection
from .scheduler import build_scheduler
from .sources.telegram_channels import ensure_session_from_env
from .topics import build_router as build_topics_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    ensure_session_from_env(settings.telethon_session_b64)

    db = Database(settings.db_path)
    await db.connect()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    text_ai = TextAI(settings.anthropic_api_key, settings.text_model)
    image_ai = ImageAI(
        settings.openai_api_key,
        settings.image_model,
        settings.image_size,
        settings.image_style,
        BASE_DIR / "data" / "images",
    )

    services = Services(bot=bot, db=db, settings=settings, text_ai=text_ai, image_ai=image_ai)

    dp.include_router(build_moderation_router(services))
    dp.include_router(build_topics_router(services))
    dp.include_router(build_admin_router(services))

    async def scheduled_run() -> None:
        try:
            await start_topic_selection(services)
        except Exception:
            logger.exception("Scheduled topic selection run failed")

    scheduler = build_scheduler(
        scheduled_run,
        settings.interval_days,
        settings.schedule_time,
        settings.timezone,
    )
    scheduler.start()

    logger.info("Bot started, polling for updates")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
