from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import ROOT

STATE_PATH = ROOT / "state" / "seen.json"


class State:
    def __init__(self, seen: dict[str, str] | None = None, seeded: list[str] | None = None):
        self.seen: dict[str, str] = seen or {}
        self.seeded: set[str] = set(seeded or [])

    @classmethod
    def load(cls, path: Path = STATE_PATH) -> "State":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(data.get("seen"), data.get("seeded"))

    def save(self, path: Path = STATE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"seeded": sorted(self.seeded), "seen": dict(sorted(self.seen.items()))}
        path.write_text(json.dumps(payload, indent=0) + "\n", encoding="utf-8")

    def mark(self, ids, now: datetime | None = None) -> None:
        stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        for i in ids:
            self.seen.setdefault(i, stamp)

    def prune(self, ttl_days: int, now: datetime | None = None) -> None:
        cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=ttl_days)
        self.seen = {k: v for k, v in self.seen.items() if datetime.fromisoformat(v) >= cutoff}
