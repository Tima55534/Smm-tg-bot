from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from aiogram import Bot, Router
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from .config import Settings
from .db import Database, Draft

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

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


async def _publish_to_channel(bot: Bot, channel_id: str, draft: Draft) -> None:
    if draft.kind == "post":
        await bot.send_photo(
            channel_id,
            photo=FSInputFile(draft.image_path),
            caption=(draft.body or "")[:1024],
        )
    else:
        await bot.send_poll(
            channel_id,
            question=draft.poll_question,
            options=draft.poll_options,
            is_anonymous=True,
        )


async def _publish_to_channel_logged(bot: Bot, channel_id: str, draft_id: int, draft: Draft) -> None:
    try:
        await _publish_to_channel(bot, channel_id, draft)
    except Exception:
        logger.exception("Delayed publish of draft %s to channel %s failed", draft_id, channel_id)


async def publish_draft(
    bot: Bot,
    db: Database,
    settings: Settings,
    draft_id: int,
    scheduler: "AsyncIOScheduler | None" = None,
) -> tuple[list[str], list[str]]:
    """Publish to the first configured channel immediately; every channel
    after that is delayed by `secondary_channel_delay_minutes` (0 = also
    immediate). Returns (immediate_errors, delayed_channel_ids) — raises
    only if the first (immediate) channel fails, since that's the one the
    admin is actively waiting on."""
    draft = await db.get_draft(draft_id)
    if draft is None:
        raise ValueError(f"Draft {draft_id} not found")

    channels = settings.target_channel_ids
    if not channels:
        raise RuntimeError("No target channels configured")

    immediate_channel, *rest = channels
    delay = settings.secondary_channel_delay_minutes

    errors: list[str] = []
    try:
        await _publish_to_channel(bot, immediate_channel, draft)
    except Exception as exc:
        logger.exception("Failed to publish draft %s to channel %s", draft_id, immediate_channel)
        raise RuntimeError(f"{immediate_channel}: {exc}") from exc

    await db.set_status(draft_id, "published")

    scheduled_channels: list[str] = []
    if rest and delay > 0 and scheduler is not None:
        run_at = datetime.now(ZoneInfo(settings.timezone)) + timedelta(minutes=delay)
        for i, channel_id in enumerate(rest):
            scheduler.add_job(
                _publish_to_channel_logged,
                trigger="date",
                run_date=run_at,
                args=[bot, channel_id, draft_id, draft],
                id=f"delayed_publish_{draft_id}_{i}",
                replace_existing=True,
            )
            scheduled_channels.append(channel_id)
        logger.info("Scheduled delayed publish of draft %s to %s at %s", draft_id, rest, run_at)
    else:
        for channel_id in rest:
            try:
                await _publish_to_channel(bot, channel_id, draft)
            except Exception as exc:
                logger.exception("Failed to publish draft %s to channel %s", draft_id, channel_id)
                errors.append(f"{channel_id}: {exc}")

    return errors, scheduled_channels


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
                errors, scheduled = await publish_draft(
                    services.bot, services.db, services.settings, draft_id, services.scheduler
                )
            except Exception:
                logger.exception("Failed to publish draft %s", draft_id)
                await callback.answer("Ошибка публикации, см. логи", show_alert=True)
                return
            await callback.message.edit_reply_markup(reply_markup=None)
            if errors:
                await callback.message.reply(
                    f"Опубликовано (черновик #{draft_id}), но не во все каналы ⚠️\n"
                    f"Ошибки: {'; '.join(errors)}"
                )
                await callback.answer("Опубликовано частично", show_alert=True)
            elif scheduled:
                delay = services.settings.secondary_channel_delay_minutes
                await callback.message.reply(
                    f"Опубликовано (черновик #{draft_id}) ✅\n"
                    f"В остальные каналы уйдёт через {delay} мин.: {', '.join(scheduled)}"
                )
                await callback.answer("Опубликовано")
            else:
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
