from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from .config import Settings
from .db import Database, TopicBatchItem
from .pipeline import generate_draft_for_item
from .sources.base import NewsItem

if TYPE_CHECKING:
    from .pipeline import Services

logger = logging.getLogger(__name__)


def _build_keyboard(items: list[TopicBatchItem]) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        mark = "✅" if item.selected else "⬜"
        label = f"{mark} {item.idx + 1}. {item.title[:55]}"
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=f"topic:{item.batch_id}:t:{item.id}")]
        )
    if items:
        rows.append(
            [InlineKeyboardButton(text="Готово ✅", callback_data=f"topic:{items[0].batch_id}:confirm")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_text(items: list[TopicBatchItem]) -> str:
    lines = ["Выберите темы для постов (нажмите на тему, чтобы отметить/снять):", ""]
    for item in items:
        mark = "✅" if item.selected else "⬜"
        lines.append(f"{mark} {item.idx + 1}. {html.escape(item.title)}")
        if item.gloss and item.gloss != item.title:
            lines.append(f"    <i>{html.escape(item.gloss)}</i>")
    return "\n".join(lines)


def _item_to_news_item(item: TopicBatchItem) -> NewsItem:
    return NewsItem(
        source=item.source,
        external_id=item.external_id,
        title=item.title,
        text=item.text,
        url=item.url,
        published_at=item.published_at,
    )


async def send_topic_batch(bot: Bot, db: Database, settings: Settings, batch_id: int) -> None:
    items = await db.get_topic_batch_items(batch_id)
    if not items:
        return
    message = await bot.send_message(
        settings.moderation_chat_id,
        _build_text(items),
        reply_markup=_build_keyboard(items),
    )
    await db.set_topic_batch_moderation_message(batch_id, message.chat.id, message.message_id)


def build_router(services: "Services") -> Router:
    router = Router(name="topics")

    @router.callback_query(lambda c: c.data and c.data.startswith("topic:"))
    async def on_topic_action(callback: CallbackQuery) -> None:
        parts = callback.data.split(":")
        batch_id = int(parts[1])
        action = parts[2]

        batch = await services.db.get_topic_batch(batch_id)
        if batch is None:
            await callback.answer("Подборка не найдена", show_alert=True)
            return
        if batch.status != "pending":
            await callback.answer("Уже подтверждено", show_alert=True)
            return

        if action == "t":
            item_id = int(parts[3])
            await services.db.toggle_topic_item(item_id)
            items = await services.db.get_topic_batch_items(batch_id)
            await callback.message.edit_text(_build_text(items), reply_markup=_build_keyboard(items))
            await callback.answer()
            return

        if action == "confirm":
            items = await services.db.get_topic_batch_items(batch_id)
            await services.db.set_topic_batch_status(batch_id, "confirmed")
            await callback.message.edit_reply_markup(reply_markup=None)

            for item in items:
                await services.db.record_topic_feedback(
                    item.source, item.external_id, item.title, item.selected
                )

            selected_items = [i for i in items if i.selected]
            if not selected_items:
                await callback.message.reply("Ни одна тема не выбрана.")
                await callback.answer()
                return

            await callback.message.reply(f"Принято, готовлю {len(selected_items)} черновик(ов)...")
            for item in selected_items:
                await services.db.mark_seen(item.source, item.external_id)
                try:
                    await generate_draft_for_item(services, _item_to_news_item(item))
                except Exception:
                    logger.exception("Failed to generate draft for topic item %s", item.id)
            await callback.answer("Готово")
            return

        await callback.answer()

    return router
