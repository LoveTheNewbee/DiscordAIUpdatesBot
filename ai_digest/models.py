from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Item:
    id: str
    title: str
    url: str
    source: str
    tier: int
    category: str
    published: datetime  # timezone-aware UTC
    summary: str = ""
    image: str | None = None
    popularity: float = 0.0  # already normalised to a 0-30 score bonus by the fetcher
    score: float = 0.0
