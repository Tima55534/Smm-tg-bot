from __future__ import annotations

import json
import re

from anthropic import AsyncAnthropic

from ..sources.base import NewsItem

# Telegram photo caption limit is 1024 chars; leave headroom for the AI's imprecision.
POST_CHAR_BUDGET = 900

POST_PROMPT = """\
{style}

Источник: {source}
Заголовок: {title}
Текст новости:
{text}

Перепиши это в готовый пост для Telegram-канала (не длиннее {budget} символов,
включая пробелы). Ответь ТОЛЬКО текстом поста, без пояснений и без markdown-заголовков."""

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
        return text[:1024]

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
