from __future__ import annotations

import json
import re

from anthropic import AsyncAnthropic

from ..sources.base import NewsItem

# Telegram photo caption limit is 1024 chars; leave headroom for HTML tags and
# the AI's imprecision so truncation (which could cut a tag in half) is rare.
POST_CHAR_BUDGET = 750

POST_PROMPT = """\
{style}

Источник: {source}
Заголовок: {title}
Текст новости:
{text}

Перепиши это в готовый пост для Telegram-канала (весь видимый текст не длиннее
{budget} символов, включая пробелы — HTML-теги в этот лимит не считаются).

Форматирование — строго HTML-подмножество, которое понимает Telegram Bot API:
разрешены только теги <b>, <i>, <blockquote>, ничего больше (никакого markdown
вроде ** или ##, никаких <p>, <div>, <ul>, <li>). Каждый открытый тег должен
быть закрыт. Ответь ТОЛЬКО готовым HTML-текстом поста, без пояснений от себя."""

POLL_PROMPT = """\
На основе этой новости сформулируй опрос для Telegram-канала на русском языке.

Заголовок: {title}
Текст:
{text}

Ответь строго в формате JSON без каких-либо пояснений:
{{"question": "...", "options": ["...", "...", "..."]}}

Требования: question до 250 символов, от 2 до 5 вариантов ответа,
каждый вариант до 90 символов, варианты короткие и осмысленные."""


class TextAI:
    def __init__(self, api_key: str, model: str):
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def rewrite_post(self, item: NewsItem, style: str) -> str:
        prompt = POST_PROMPT.format(
            style=style.strip(),
            source=item.source,
            title=item.title,
            text=item.text[:6000],
            budget=POST_CHAR_BUDGET,
        )
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()
        if len(text) > 1024:
            # Claude ignored the budget; better to drop the whole block-quote tail
            # than to risk truncating mid-tag and breaking Telegram's HTML parser.
            text = text[:1024].rsplit("<", 1)[0].rstrip()
        return text

    async def generate_poll(self, item: NewsItem) -> tuple[str, list[str]]:
        prompt = POLL_PROMPT.format(title=item.title, text=item.text[:4000])
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(block.text for block in message.content if block.type == "text").strip()

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError(f"Claude did not return JSON for poll: {raw!r}")

        data = json.loads(match.group(0))
        question = str(data["question"])[:250]
        options = [str(opt)[:90] for opt in data["options"]][:5]
        if len(options) < 2:
            raise ValueError(f"Poll needs at least 2 options, got: {options!r}")
        return question, options
