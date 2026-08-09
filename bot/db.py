from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_items (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    seen_at REAL NOT NULL,
    PRIMARY KEY (source, external_id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- 'post' or 'poll'
    source TEXT,
    external_id TEXT,
    source_url TEXT,
    title TEXT,
    body TEXT,
    image_path TEXT,
    poll_question TEXT,
    poll_options TEXT,                  -- JSON list
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/approved/rejected/published
    moderation_chat_id INTEGER,
    moderation_message_id INTEGER,
    created_at REAL NOT NULL,
    published_at REAL,
    post_count_at_creation INTEGER NOT NULL DEFAULT 0
);
"""


@dataclass
class Draft:
    id: int
    kind: str
    source: Optional[str]
    external_id: Optional[str]
    source_url: Optional[str]
    title: Optional[str]
    body: Optional[str]
    image_path: Optional[str]
    poll_question: Optional[str]
    poll_options: list[str]
    status: str
    moderation_chat_id: Optional[int]
    moderation_message_id: Optional[int]
    created_at: float
    published_at: Optional[float]
    post_count_at_creation: int

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Draft":
        return cls(
            id=row["id"],
            kind=row["kind"],
            source=row["source"],
            external_id=row["external_id"],
            source_url=row["source_url"],
            title=row["title"],
            body=row["body"],
            image_path=row["image_path"],
            poll_question=row["poll_question"],
            poll_options=json.loads(row["poll_options"]) if row["poll_options"] else [],
            status=row["status"],
            moderation_chat_id=row["moderation_chat_id"],
            moderation_message_id=row["moderation_message_id"],
            created_at=row["created_at"],
            published_at=row["published_at"],
            post_count_at_creation=row["post_count_at_creation"],
        )


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "Database not connected"
        return self._conn

    # -- dedup --------------------------------------------------------

    async def is_seen(self, source: str, external_id: str) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM seen_items WHERE source = ? AND external_id = ?",
            (source, external_id),
        )
        row = await cur.fetchone()
        return row is not None

    async def mark_seen(self, source: str, external_id: str) -> None:
        await self.conn.execute(
            "INSERT OR IGNORE INTO seen_items (source, external_id, seen_at) VALUES (?, ?, ?)",
            (source, external_id, time.time()),
        )
        await self.conn.commit()

    # -- drafts ---------------------------------------------------------

    async def create_draft(
        self,
        kind: str,
        source: Optional[str] = None,
        external_id: Optional[str] = None,
        source_url: Optional[str] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        image_path: Optional[str] = None,
        poll_question: Optional[str] = None,
        poll_options: Optional[list[str]] = None,
    ) -> int:
        published_count = await self.count_published()
        cur = await self.conn.execute(
            """INSERT INTO drafts
               (kind, source, external_id, source_url, title, body, image_path,
                poll_question, poll_options, status, created_at, post_count_at_creation)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                kind,
                source,
                external_id,
                source_url,
                title,
                body,
                image_path,
                poll_question,
                json.dumps(poll_options or [], ensure_ascii=False),
                time.time(),
                published_count,
            ),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def get_draft(self, draft_id: int) -> Optional[Draft]:
        cur = await self.conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
        row = await cur.fetchone()
        return Draft.from_row(row) if row else None

    async def set_moderation_message(self, draft_id: int, chat_id: int, message_id: int) -> None:
        await self.conn.execute(
            "UPDATE drafts SET moderation_chat_id = ?, moderation_message_id = ? WHERE id = ?",
            (chat_id, message_id, draft_id),
        )
        await self.conn.commit()

    async def set_status(self, draft_id: int, status: str) -> None:
        published_at = time.time() if status == "published" else None
        if published_at is not None:
            await self.conn.execute(
                "UPDATE drafts SET status = ?, published_at = ? WHERE id = ?",
                (status, published_at, draft_id),
            )
        else:
            await self.conn.execute(
                "UPDATE drafts SET status = ? WHERE id = ?", (status, draft_id)
            )
        await self.conn.commit()

    async def count_published(self) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS c FROM drafts WHERE status = 'published'"
        )
        row = await cur.fetchone()
        return int(row["c"])

    async def latest_drafts(self, limit: int = 10) -> list[Draft]:
        cur = await self.conn.execute(
            "SELECT * FROM drafts ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cur.fetchall()
        return [Draft.from_row(r) for r in rows]
