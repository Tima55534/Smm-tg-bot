from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from .config import Settings
from .db import Database

if TYPE_CHECKING:
    from .pipeline import Services

logger = logging.getLogger(__name__)


def _keyboard(draft_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Опубликовать", callback_data=f"draft:{draft_id}:approve"),
                InlineKeyboardButton(text="Отклонить", callback_data=f"draft:{draft_id}:reject"),
            ]
        ]
    )


async def send_draft_for_moderation(
    bot: Bot, db: Database, settings: Settings, draft_id: int
) -> None:
    draft = await db.get_draft(draft_id)
    if draft is None:
        logger.error("send_draft_for_moderation: draft %s not found", draft_id)
        return

    kb = _keyboard(draft_id)

    if draft.kind == "post":
        caption = f"{draft.body or ''}\n\n— черновик #{draft_id}"
        if len(caption) > 1024:
            # draft.body is already <=1024 and HTML-tag-safe; drop the footer
            # rather than risk cutting a tag in half.
            caption = draft.body or ""
        message = await bot.send_photo(
            settings.moderation_chat_id,
            photo=FSInputFile(draft.image_path),
            caption=caption,
            reply_markup=kb,
        )
    else:
        options_text = "\n".join(f"• {html.escape(o)}" for o in draft.poll_options)
        question = html.escape(draft.poll_question or "")
        text = f"Опрос (черновик #{draft_id})\n\n{question}\n\n{options_text}"
        message = await bot.send_message(settings.moderation_chat_id, text, reply_markup=kb)

    await db.set_moderation_message(draft_id, message.chat.id, message.message_id)


async def publish_draft(bot: Bot, db: Database, settings: Settings, draft_id: int) -> None:
    draft = await db.get_draft(draft_id)
    if draft is None:
        raise ValueError(f"Draft {draft_id} not found")

    if draft.kind == "post":
        await bot.send_photo(
            settings.target_channel_id,
            photo=FSInputFile(draft.image_path),
            caption=(draft.body or "")[:1024],
        )
    else:
        await bot.send_poll(
            settings.target_channel_id,
            question=draft.poll_question,
            options=draft.poll_options,
            is_anonymous=True,
        )

    await db.set_status(draft_id, "published")


def build_router(services: "Services") -> Router:
    router = Router(name="moderation")

    @router.callback_query(lambda c: c.data and c.data.startswith("draft:"))
    async def on_moderation_action(callback: CallbackQuery) -> None:
        _, draft_id_str, action = callback.data.split(":")
        draft_id = int(draft_id_str)
        draft = await services.db.get_draft(draft_id)

        if draft is None:
            await callback.answer("Черновик не найден", show_alert=True)
            return
        if draft.status != "pending":
            await callback.answer(f"Уже обработан ({draft.status})", show_alert=True)
            return

        if action == "approve":
            try:
                await publish_draft(services.bot, services.db, services.settings, draft_id)
            except Exception:
                logger.exception("Failed to publish draft %s", draft_id)
                await callback.answer("Ошибка публикации, см. логи", show_alert=True)
                return
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.reply(f"Опубликовано (черновик #{draft_id}) ✅")
            await callback.answer("Опубликовано")
        elif action == "reject":
            await services.db.set_status(draft_id, "rejected")
            await callback.message.edit_reply_markup(reply_markup=None)
            await callback.message.reply(f"Отклонено (черновик #{draft_id}) ❌")
            await callback.answer("Отклонено")
        else:
            await callback.answer()

    return router
