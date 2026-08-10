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

GLOSS_PROMPT = """\
Вот список тем новостей (заголовки могут быть хэштегами или неинформативными),
и краткий текст к каждой:

{items}

Для каждой темы напиши 1-2 предложения на русском (примерно 20-40 слов),
которые понятным языком объясняют редактору: (а) что означает заголовок,
если это хэштег или неочевидная фраза, и (б) о чём именно эта новость —
конкретные факты, а не общие слова. Редактор должен понять суть, не открывая
источник. Если это не новость, а реклама/розыгрыш/шаблонный пост — прямо
скажи об этом.

Ответь СТРОГО JSON-массивом из {count} строк в том же порядке, без пояснений.
Пример формата: ["Меняются сроки сдачи НДС: с 2027 года отчёт нужно подавать
до 15 числа вместо 20-го, коснётся всех плательщиков НДС", "Рекламный
розыгрыш от банка среди держателей карт — не новость, для канала не подходит"]"""

IMAGE_BRIEF_PROMPT = """\
Заголовок новости: {title}
Текст: {text}

Опиши ОДНИМ предложением на английском языке, какой конкретный физический
объект или сцена лучше всего символизировала бы именно эту новость на
постерной 3D-иллюстрации (например: "a 3D rendered car key with a glowing
ribbon", "a stack of tax documents with a calendar page", "a 3D coin stack
with an upward arrow"). Не описывай стиль/свет/цвет — только сам объект/сцену,
это добавится отдельно. Ответь только этим предложением, без пояснений."""

RELEVANCE_PROMPT = """\
Ты помогаешь редактору Telegram-канала для начинающих бухгалтеров-стажёров
отбирать темы новостей. Не все новости про налоги и бухгалтерию им подходят —
некоторые слишком сложные, узкоспециализированные или нерелевантные новичкам.

Заголовки, которые редактор УЖЕ ОДОБРИЛ в прошлом (значит, такой уровень
сложности и такие темы подходят):
{accepted}

Заголовки, которые редактор ОТКЛОНИЛ (не подходят новичкам):
{rejected}

Теперь оцени вот эти новые кандидаты (пронумерованы):
{candidates}

Ответь СТРОГО JSON-массивом из {count} значений true/false в том же порядке
(true = стоит предложить редактору, false = не стоит), без пояснений.
Пример формата: [true, false, true]"""


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
        if len(text) < 150:
            # The source item probably had too little real content to work
            # with — better to fail loudly than send a threadbare post.
            raise ValueError(f"Generated post looks too short/broken: {text!r}")
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

    async def suggest_topic_relevance(
        self,
        candidates: list[NewsItem],
        accepted_titles: list[str],
        rejected_titles: list[str],
    ) -> list[bool]:
        """Pre-check which candidate topics look relevant, based on past admin
        decisions. Returns a list of bools, same order/length as `candidates`.
        Fails safe to all-False (nothing pre-checked) on any error."""
        if not accepted_titles and not rejected_titles:
            return [False] * len(candidates)

        candidates_text = "\n".join(
            f"{i + 1}. {item.title}" for i, item in enumerate(candidates)
        )
        prompt = RELEVANCE_PROMPT.format(
            accepted="\n".join(f"- {t}" for t in accepted_titles) or "(пока нет)",
            rejected="\n".join(f"- {t}" for t in rejected_titles) or "(пока нет)",
            candidates=candidates_text,
            count=len(candidates),
        )
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(
                block.text for block in message.content if block.type == "text"
            ).strip()
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON array in response: {raw!r}")
            values = json.loads(match.group(0))
            if len(values) != len(candidates):
                raise ValueError(f"Expected {len(candidates)} values, got {len(values)}")
            return [bool(v) for v in values]
        except Exception:
            return [False] * len(candidates)

    async def summarize_topics(self, candidates: list[NewsItem]) -> list[str]:
        """One-line, plain-language Russian gloss per candidate, so the admin
        can judge a topic without decoding a hashtag or a vague headline.
        Falls back to the raw title on any error."""
        fallback = [item.title for item in candidates]
        items_text = "\n\n".join(
            f"{i + 1}. Заголовок: {item.title}\n   Текст: {item.text[:600]}"
            for i, item in enumerate(candidates)
        )
        prompt = GLOSS_PROMPT.format(items=items_text, count=len(candidates))
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(
                block.text for block in message.content if block.type == "text"
            ).strip()
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON array in response: {raw!r}")
            values = json.loads(match.group(0))
            if len(values) != len(candidates):
                raise ValueError(f"Expected {len(candidates)} values, got {len(values)}")
            return [str(v)[:350] for v in values]
        except Exception:
            return fallback

    async def suggest_image_brief(self, item: NewsItem) -> str | None:
        """A short, content-specific description of what the illustration's
        hero object/scene should be, so the image isn't a generic stand-in.
        Returns None on any error (caller should fall back to the bare title)."""
        prompt = IMAGE_BRIEF_PROMPT.format(title=item.title, text=item.text[:2000])
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in message.content if block.type == "text"
            ).strip()
            return text or None
        except Exception:
            return None
