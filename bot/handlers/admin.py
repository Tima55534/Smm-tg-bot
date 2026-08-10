from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..pipeline import run_pipeline, start_topic_selection

if TYPE_CHECKING:
    from ..pipeline import Services

logger = logging.getLogger(__name__)

STATUS_LABELS = {
    "pending": "на модерации",
    "approved": "одобрен",
    "rejected": "отклонён",
    "published": "опубликован",
}


def build_router(services: "Services") -> Router:
    router = Router(name="admin")

    def _is_admin(message: Message) -> bool:
        return message.chat.id == services.settings.moderation_chat_id

    @router.message(Command("now"))
    async def cmd_now(message: Message) -> None:
        if not _is_admin(message):
            return
        await message.reply("Собираю темы из источников...")
        try:
            batch_id = await start_topic_selection(services)
        except Exception:
            logger.exception("Manual /now run failed")
            await message.reply("Ошибка при сборе тем, см. логи сервера.")
            return
        if batch_id is None:
            await message.reply("Свежих новостей не найдено ни в одном источнике.")

    @router.message(Command("poll"))
    async def cmd_poll(message: Message) -> None:
        if not _is_admin(message):
            return
        await message.reply("Готовлю опрос по последней новости...")
        try:
            draft_id = await run_pipeline(services, force_kind="poll")
        except Exception:
            logger.exception("Manual /poll run failed")
            await message.reply("Ошибка при подготовке опроса, см. логи сервера.")
            return
        if draft_id is None:
            await message.reply("Свежих новостей не найдено ни в одном источнике.")

    @router.message(Command("status"))
    async def cmd_status(message: Message) -> None:
        if not _is_admin(message):
            return
        drafts = await services.db.latest_drafts(limit=10)
        if not drafts:
            await message.reply("Черновиков пока нет.")
            return
        lines = []
        for d in drafts:
            when = datetime.fromtimestamp(d.created_at).strftime("%d.%m %H:%M")
            title = d.title or d.poll_question or ""
            lines.append(f"#{d.id} [{d.kind}] {STATUS_LABELS.get(d.status, d.status)} — {when} — {title[:60]}")
        await message.reply("\n".join(lines))

    return router
