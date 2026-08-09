from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot

from .ai.image import ImageAI
from .ai.text import TextAI
from .config import Settings
from .db import Database
from .moderation import send_draft_for_moderation
from .sources import buxgalter, soliq, telegram_channels
from .sources.base import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class Services:
    bot: Bot
    db: Database
    settings: Settings
    text_ai: TextAI
    image_ai: ImageAI


async def collect_candidates(settings: Settings, db: Database) -> list[NewsItem]:
    items: list[NewsItem] = []

    for web_source in settings.web_sources:
        try:
            if web_source.type == "buxgalter":
                items += await buxgalter.fetch(
                    web_source.options["url"], limit=settings.max_items_per_source
                )
            elif web_source.type == "soliq":
                items += await soliq.fetch(
                    web_source.options["api_url"],
                    web_source.options["file_url"],
                    limit=settings.max_items_per_source,
                    page_size=web_source.options.get("page_size", 10),
                )
            else:
                logger.warning("Unknown web source type: %s", web_source.type)
        except Exception:
            logger.exception("Failed to fetch web source %s", web_source.name)

    try:
        items += await telegram_channels.fetch_all(
            settings.telegram_api_id,
            settings.telegram_api_hash,
            settings.telegram_channels,
            limit=settings.max_items_per_source,
        )
    except Exception:
        logger.exception("Failed to fetch Telegram channel sources")

    unseen: list[NewsItem] = []
    for item in items:
        if not await db.is_seen(item.source, item.external_id):
            unseen.append(item)

    unseen.sort(key=lambda i: i.published_at or 0, reverse=True)
    return unseen


async def run_pipeline(services: Services, force_kind: str | None = None) -> int | None:
    """Fetch fresh candidates, build a draft, send it for moderation.

    Returns the created draft id, or None if there was no fresh item to post.
    """
    candidates = await collect_candidates(services.settings, services.db)
    if not candidates:
        logger.info("No fresh, unseen items found across all sources")
        return None

    item = candidates[0]
    await services.db.mark_seen(item.source, item.external_id)

    kind = force_kind
    if kind is None:
        published = await services.db.count_published()
        next_index = published + 1
        poll_every = services.settings.poll_every_n_posts
        kind = "poll" if poll_every and next_index % poll_every == 0 else "post"

    if kind == "poll":
        question, options = await services.text_ai.generate_poll(item)
        draft_id = await services.db.create_draft(
            kind="poll",
            source=item.source,
            external_id=item.external_id,
            source_url=item.url,
            title=item.title,
            poll_question=question,
            poll_options=options,
        )
    else:
        body = await services.text_ai.rewrite_post(item, services.settings.post_style)
        image_path = await services.image_ai.generate(item.title)
        draft_id = await services.db.create_draft(
            kind="post",
            source=item.source,
            external_id=item.external_id,
            source_url=item.url,
            title=item.title,
            body=body,
            image_path=str(image_path),
        )

    await send_draft_for_moderation(services.bot, services.db, services.settings, draft_id)
    return draft_id
