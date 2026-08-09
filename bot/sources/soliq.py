from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import NewsItem

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SmmNewsBot/1.0)",
    "Content-Type": "application/json",
}


def _strip_html(html: str) -> str:
    return BeautifulSoup(html or "", "lxml").get_text(" ", strip=True)


def _parse_date(value: str) -> float | None:
    # e.g. "10.06.2026 09:50 AM"
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d.%m.%Y %I:%M %p").timestamp()
    except ValueError:
        return None


async def fetch(api_url: str, file_url: str, limit: int = 5, page_size: int = 10) -> list[NewsItem]:
    payload = {"page": 0, "size": max(limit, page_size)}

    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0) as client:
        resp = await client.post(api_url, json=payload)
        resp.raise_for_status()

    data = resp.json()
    items: list[NewsItem] = []

    for entry in data.get("list", [])[:limit]:
        external_id = str(entry.get("id"))
        title = (entry.get("title") or "").strip()
        description = (entry.get("description") or "").strip()
        body = _strip_html(entry.get("content") or "")
        text = "\n".join(filter(None, [title, description, body]))[:4000]

        image_url = None
        file_name = entry.get("fileName")
        if file_name:
            image_url = file_url.format(file_name=file_name)

        items.append(
            NewsItem(
                source="soliq_uz",
                external_id=external_id,
                title=title,
                text=text,
                image_url=image_url,
                published_at=_parse_date(entry.get("publishDate") or entry.get("date")),
            )
        )

    return items
