from __future__ import annotations

import re
from datetime import datetime, timezone

from .config import Config
from .models import Item

TIER_BASE = {1: 100, 2: 60, 3: 30}


def compute_score(item: Item, cfg: Config, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    s = float(TIER_BASE.get(item.tier, 30))
    if cfg.release_re.search(item.title):
        s += 20
    if cfg.model_re.search(item.title):
        s += 15
    s += item.popularity
    age_h = max(0.0, (now - item.published).total_seconds() / 3600)
    s += max(0.0, 10 - age_h / 6)  # up to +10 for very fresh items
    return round(s, 1)


def passes_filter(item: Item, src: dict, cfg: Config) -> bool:
    for pat in src.get("exclude_title", []):
        if re.search(pat, item.title, re.I):
            return False
    mode = src.get("filter")
    if mode == "ai":
        text = f"{item.title} {item.summary}"
        return bool(cfg.ai_re.search(text) or cfg.model_re.search(text))
    if mode == "release":
        return bool(cfg.release_re.search(item.title) or cfg.model_re.search(item.title))
    return True
