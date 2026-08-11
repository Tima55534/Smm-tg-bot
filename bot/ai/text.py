from __future__ import annotations

import json
import logging
import re

from anthropic import AsyncAnthropic

from ..sources.base import NewsItem

logger = logging.getLogger(__name__)

CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")

TRANSLITERATE_PROMPT = """\
Quyidagi matnda ba'zi joylari Kirill yozuvida qolib ketgan (bo'lishi kerak
emas). Butun matnni, so'zma-so'z, faqat yozuvni Kirilldan lotin o'zbek
yozuviga o'tkazib qayta yoz — mazmunni, uslubni, barcha HTML teglarini
(<b>, <i>, <blockquote> va h.k.) va formatlashni ANIQ saqlab qol, hech narsa
qo'shma yoki olib tashlama. Javobda faqat lotin yozuvidagi matnni ber, hech
qanday izohsiz:

{text}"""

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
быть закрыт.

ВАЖНО про алфавит: пиши ИСКЛЮЧИТЕЛЬНО латиницей (o'zbek lotin alifbosi), даже
если исходная новость на русском или узбекской кириллице. НЕ используй ни
одной кириллической буквы (никаких а, б, в, г, ў, қ, ғ, ҳ и т.д.) — включая
названия, термины и цифры-прописью из источника: их тоже нужно передать
латиницей. Это правило важнее стиля источника.

Ответь ТОЛЬКО готовым HTML-текстом поста, без пояснений от себя."""

POLL_PROMPT = """\
На основе этой новости сформулируй опрос для Telegram-канала.

Заголовок: {title}
Текст:
{text}

Ответь строго в формате JSON без каких-либо пояснений:
{{"question": "...", "options": ["...", "...", "..."]}}

Требования: question до 250 символов, от 2 до 5 вариантов ответа,
каждый вариант до 90 символов, варианты короткие и осмысленные.

ВАЖНО про язык и алфавит: question и все options — ИСКЛЮЧИТЕЛЬНО на
узбекском языке латиницей (o'zbek lotin alifbosi), даже если заголовок/текст
новости на русском или узбекской кириллице. Ни одной кириллической буквы в
ответе быть не должно."""

GLOSS_PROMPT = """\
Вот список тем новостей (заголовки могут быть хэштегами или неинформативными),
и краткий текст к каждой:

{items}

Har bir mavzu uchun ROVNO BITTA gap yoz — o'zbek tilida, LOTIN yozuvida (Kirill
emas), 25 so'zdan OSHMASIN (bu qat'iy chegara, so'zlarni sanab chiq). Gap
muharrirga tushunarli tilda tushuntirsin: sarlavha nimani anglatadi (agar bu
hashtag yoki noaniq ibora bo'lsa) VA aynan qanday xabar — asosiy fakt, ortiqcha
tafsilotlarsiz. Muharrir manbani ochmasdan mohiyatni tushunishi kerak. Agar bu
yangilik emas, balki reklama/lotereya/shablon post bo'lsa — "[yangilik emas]"
belgisidan boshla.

Javobni QAT'IY {count} ta qatordan iborat JSON-massiv sifatida ber, xuddi shu
tartibda, izohlarsiz va Markdown'siz. Massivning har bir qatori — bitta
qatorli JSON-satr, ICHIDA qator ko'chirish (newline) BO'LMASIN.
Format namunasi (aynan shunday, har bir element — bitta qisqa gap):
["2027-yildan QQS 20-sana o'rniga 15-sanagacha topshiriladi.", "[yangilik emas] Bank kartasi egalari orasida reklama lotereyasi."]"""

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

    async def _transliterate_to_latin(self, text: str) -> str:
        prompt = TRANSLITERATE_PROMPT.format(text=text)
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()

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
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in message.content if block.type == "text").strip()

        if CYRILLIC_RE.search(text):
            # Claude sometimes mirrors the source script (Russian/Uzbek Cyrillic)
            # instead of following the Latin-script instruction — fix it up
            # with a dedicated transliteration pass rather than shipping it.
            logger.warning("rewrite_post produced Cyrillic text, retrying as transliteration")
            text = await self._transliterate_to_latin(text)

        if len(text) > 1024:
            # Claude ignored the budget; better to drop the whole block-quote tail
            # than to risk truncating mid-tag and breaking Telegram's HTML parser.
            text = text[:1024].rsplit("<", 1)[0].rstrip()
        if len(text) < 150:
            # The source item probably had too little real content to work
            # with — better to fail loudly than send a threadbare post.
            raise ValueError(f"Generated post looks too short/broken: {text!r}")
        if CYRILLIC_RE.search(text):
            raise ValueError(f"Generated post still has Cyrillic after retry: {text!r}")
        return text

    async def generate_poll(self, item: NewsItem) -> tuple[str, list[str]]:
        prompt = POLL_PROMPT.format(title=item.title, text=item.text[:4000])
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=1000,
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

        if CYRILLIC_RE.search(question) or any(CYRILLIC_RE.search(o) for o in options):
            logger.warning("generate_poll produced Cyrillic text, retrying as transliteration")
            question = await self._transliterate_to_latin(question)
            options = [await self._transliterate_to_latin(o) for o in options]
            if CYRILLIC_RE.search(question) or any(CYRILLIC_RE.search(o) for o in options):
                raise ValueError(f"Poll still has Cyrillic after retry: {question!r} {options!r}")

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
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = "".join(
                block.text for block in message.content if block.type == "text"
            ).strip()
            match = re.search(r"\[.*\]", raw, re.DOTALL)
            if not match:
                raise ValueError(f"No JSON array in response: {raw!r}")
            array_text = match.group(0)
            try:
                values = json.loads(array_text)
            except json.JSONDecodeError:
                # Claude sometimes wraps a line inside a string value despite
                # instructions not to — raw newlines inside a JSON string are
                # invalid, so collapse them and retry once.
                values = json.loads(re.sub(r"(?<!\\)\n", " ", array_text))
            if len(values) != len(candidates):
                raise ValueError(f"Expected {len(candidates)} values, got {len(values)}")
            return [str(v)[:350] for v in values]
        except Exception:
            logger.warning("summarize_topics failed, falling back to raw titles", exc_info=True)
            return fallback

    async def suggest_image_brief(self, item: NewsItem) -> str | None:
        """A short, content-specific description of what the illustration's
        hero object/scene should be, so the image isn't a generic stand-in.
        Returns None on any error (caller should fall back to the bare title)."""
        prompt = IMAGE_BRIEF_PROMPT.format(title=item.title, text=item.text[:2000])
        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in message.content if block.type == "text"
            ).strip()
            return text or None
        except Exception:
            return None
