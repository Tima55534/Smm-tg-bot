from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import NewsItem

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SmmNewsBot/1.0)"}
DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")

# Recurring calendar-reminder posts republished every month — not real news,
# so they'd otherwise crowd out everything else at the top of the feed.
SKIP_TITLE_RE = re.compile(r"^План главбуха на", re.IGNORECASE)


async def fetch(url: str, limit: int = 5) -> list[NewsItem]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    items: list[NewsItem] = []

    for block in soup.select('div.inner_no_margin[id^="pub_"]'):
        if len(items) >= limit:
            break

        link_el = block.select_one(".title_no_name a")
        if not link_el or not link_el.get("href"):
            continue

        external_id = block["id"].removeprefix("pub_")
        title = link_el.get_text(strip=True)
        if SKIP_TITLE_RE.match(title):
            continue
        href = link_el["href"]
        full_url = href if href.startswith("http") else f"https://buxgalter.uz{href}"

        excerpt_el = block.select_one(".text_no_name")
        excerpt = excerpt_el.get_text(strip=True) if excerpt_el else ""

        date_el = block.select_one(".date_text")
        published_at = None
        if date_el:
            m = DATE_RE.search(date_el.get_text())
            if m:
                published_at = datetime.strptime(m.group(1), "%d.%m.%Y").timestamp()

        items.append(
            NewsItem(
                source="buxgalter_uz",
                external_id=external_id,
                title=title,
                text=f"{title}\n{excerpt}".strip(),
                url=full_url,
                published_at=published_at,
            )
        )

    return items
