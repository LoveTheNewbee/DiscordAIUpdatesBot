from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _word_re(terms: list[str]) -> re.Pattern:
    parts = [re.escape(t.lower()) for t in terms]
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(parts) + r")(?![a-z0-9])", re.I)


@dataclass
class Config:
    settings: dict
    sources: list[dict]
    ai_re: re.Pattern
    release_re: re.Pattern
    model_re: re.Pattern


def load_config(path: Path | None = None) -> Config:
    raw = yaml.safe_load((path or ROOT / "sources.yaml").read_text(encoding="utf-8"))
    kw = raw["keywords"]
    return Config(
        settings=raw["settings"],
        sources=raw["sources"],
        ai_re=_word_re(kw["ai_terms"]),
        release_re=_word_re(kw["release_terms"]),
        model_re=_word_re(kw["model_families"]),
    )
