from __future__ import annotations

from .models import Item
from .text import title_tokens

SIMILARITY = 0.7


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def dedupe(items: list[Item]) -> list[Item]:
    """Drop repeats by id and near-identical titles, keeping the best (lowest tier, highest score)."""
    ranked = sorted(items, key=lambda i: (i.tier, -i.score))
    kept: list[Item] = []
    tokens: list[frozenset[str]] = []
    ids: set[str] = set()
    for it in ranked:
        if it.id in ids:
            continue
        tk = title_tokens(it.title)
        if any(_jaccard(tk, other) >= SIMILARITY for other in tokens):
            continue
        kept.append(it)
        tokens.append(tk)
        ids.add(it.id)
    return kept
