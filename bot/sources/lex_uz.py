from __future__ import annotations

import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from .base import NewsItem

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SmmNewsBot/1.0)"}
DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})")
DOC_ID_RE = re.compile(r"(-?\d+)$")


async def _fetch_doc_excerpt(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
    except Exception:
        return ""
    soup = BeautifulSoup(resp.text, "lxml")
    body = soup.select_one(".docBody-container")
    return body.get_text(" ", strip=True)[:3000] if body else ""


async def fetch(url: str, limit: int = 8) -> list[NewsItem]:
    async with httpx.AsyncClient(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        section = None
        for title_el in soup.select(".dd-table__title-desc"):
            if "yangilik" in title_el.get_text(strip=True).lower():
                section = title_el.find_parent("section", class_="dd-table")
                break
        if section is None:
            return []

        items: list[NewsItem] = []
        for row in section.select("tr.dd-table__main-item")[:limit]:
            link_el = row.select_one("a.lx_link")
            if not link_el or not link_el.get("href"):
                continue

            title = link_el.get_text(strip=True)
            href = link_el["href"]
            full_url = href if href.startswith("http") else f"https://lex.uz{href}"

            id_match = DOC_ID_RE.search(href)
            external_id = id_match.group(1) if id_match else href

            badge_el = row.select_one(".badge")
            badge_text = badge_el.get_text(strip=True) if badge_el else ""
            published_at = None
            date_match = DATE_RE.search(badge_text)
            if date_match:
                published_at = datetime.strptime(date_match.group(1), "%d.%m.%Y").timestamp()

            excerpt = await _fetch_doc_excerpt(client, full_url)
            text = "\n".join(filter(None, [title, badge_text, excerpt]))

            items.append(
                NewsItem(
                    source="lex_uz",
                    external_id=external_id,
                    title=title,
                    text=text,
                    url=full_url,
                    published_at=published_at,
                )
            )

    return items
