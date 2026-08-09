from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class NewsItem:
    source: str          # e.g. "soliq_uz", "buxgalter_uz", "tg:soliqnews"
    external_id: str      # stable id used for dedup, unique within `source`
    title: str
    text: str              # body / excerpt used as input for the AI rewrite
    url: Optional[str] = None
    image_url: Optional[str] = None   # source image, if any (currently unused — we AI-generate images)
    published_at: Optional[float] = None
