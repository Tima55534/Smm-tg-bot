from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from ..pipeline import run_pipeline, start_topic_selection
from ..scheduler import schedule_daily_job, schedule_job

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from ..pipeline import Services

logger = logging.getLogger(__name__)

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

STATUS_LABELS = {
    "pending": "на модерации",
    "approved": "одобрен",
    "rejected": "отклонён",
    "published": "опубликован",
}


def build_router(
    services: "Services", scheduler: "AsyncIOScheduler", scheduled_run, publish_approved_run
) -> Router:
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

    @router.message(Command("schedule"))
    async def cmd_schedule(message: Message, command: CommandObject) -> None:
        if not _is_admin(message):
            return

        args = (command.args or "").split()

        # /schedule publish [ЧЧ:ММ] — controls the OTHER job: the daily time
        # approved drafts actually get published, separate from the topic-
        # collection schedule below.
        if args and args[0] == "publish":
            publish_job = scheduler.get_job("publish_approved_job")
            next_publish = (
                publish_job.next_run_time.strftime("%d.%m.%Y %H:%M %Z") if publish_job else "?"
            )
            if len(args) == 1:
                await message.reply(
                    f"Время публикации одобренных черновиков: {services.settings.publish_time} "
                    f"({services.settings.timezone}).\nСледующий запуск: {next_publish}\n\n"
                    "Чтобы изменить: /schedule publish [ЧЧ:ММ]\nНапример: /schedule publish 12:00"
                )
                return
            if len(args) != 2 or not TIME_RE.match(args[1]):
                await message.reply(
                    "Формат: /schedule publish [ЧЧ:ММ], например /schedule publish 12:00."
                )
                return

            publish_time = args[1]
            services.settings.publish_time = publish_time
            await services.db.set_setting("publish_time", publish_time)
            schedule_daily_job(
                scheduler, publish_approved_run, publish_time, services.settings.timezone,
                "publish_approved_job",
            )
            publish_job = scheduler.get_job("publish_approved_job")
            await message.reply(
                f"Готово. Одобренные черновики теперь публикуются в {publish_time} "
                f"({services.settings.timezone}).\nСледующий запуск: "
                f"{publish_job.next_run_time.strftime('%d.%m.%Y %H:%M %Z')}"
            )
            return

        job = scheduler.get_job("pipeline_job")
        next_run = job.next_run_time.strftime("%d.%m.%Y %H:%M %Z") if job else "?"
        publish_job = scheduler.get_job("publish_approved_job")
        next_publish = (
            publish_job.next_run_time.strftime("%d.%m.%Y %H:%M %Z") if publish_job else "?"
        )

        if not args:
            await message.reply(
                "Сбор тем: раз в "
                f"{services.settings.interval_days} дн., в {services.settings.schedule_time} "
                f"({services.settings.timezone}).\nСледующий сбор тем: {next_run}\n\n"
                f"Публикация одобренного: каждый день в {services.settings.publish_time}.\n"
                f"Следующая публикация: {next_publish}\n\n"
                "Изменить сбор тем: /schedule [дни] [ЧЧ:ММ] (например /schedule 3 09:00)\n"
                "Изменить время публикации: /schedule publish [ЧЧ:ММ] (например /schedule publish 12:00)"
            )
            return

        if len(args) != 2 or not args[0].isdigit() or int(args[0]) < 1:
            await message.reply(
                "Формат: /schedule [дни] [ЧЧ:ММ], например /schedule 3 09:00 "
                "(дни — целое число ≥ 1). Или /schedule publish [ЧЧ:ММ] для времени публикации."
            )
            return

        interval_days = int(args[0])
        schedule_time = args[1]
        if not TIME_RE.match(schedule_time):
            await message.reply("Время должно быть в формате ЧЧ:ММ, например 09:00 или 18:30.")
            return

        services.settings.interval_days = interval_days
        services.settings.schedule_time = schedule_time
        await services.db.set_setting("interval_days", str(interval_days))
        await services.db.set_setting("schedule_time", schedule_time)

        next_run = schedule_job(
            scheduler, scheduled_run, interval_days, schedule_time, services.settings.timezone
        )
        await message.reply(
            f"Готово. Сбор тем теперь раз в {interval_days} дн. в {schedule_time} "
            f"({services.settings.timezone}).\nСледующий сбор тем: "
            f"{next_run.strftime('%d.%m.%Y %H:%M %Z')}"
        )

    return router
