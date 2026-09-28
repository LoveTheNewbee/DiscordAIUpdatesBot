"""Discord webhook formatting + delivery (respects embed limits and 429 rate limits)."""
from __future__ import annotations

import time
from collections import defaultdict

import httpx

from .models import Item

USERNAME = "AI Radar"
EMBEDS_PER_MESSAGE = 5  # keeps each message well under Discord's 6000-char embed total

COLORS = {"lab": 0xD97757, "release": 0x2ECC71, "hf": 0xFFD21E,
          "news": 0x3498DB, "community": 0xFF4500, "paper": 0x9B59B6}
SECTIONS = [("lab", "🧪 Labs"), ("release", "🚀 Releases"), ("hf", "🤗 Hugging Face"),
            ("news", "📰 News"), ("community", "💬 Community"), ("paper", "📄 Papers")]


def item_embed(item: Item) -> dict:
    embed = {
        "title": item.title[:256],
        "url": item.url,
        "color": COLORS.get(item.category, 0x95A5A6),
        "author": {"name": item.source},
        "timestamp": item.published.isoformat(),
    }
    if item.summary:
        embed["description"] = item.summary[:600]
    if item.image:
        embed["thumbnail"] = {"url": item.image}
    return embed


def digest_embeds(items: list[Item], date_label: str) -> list[dict]:
    """One embed per non-empty section, each a bulleted list of masked links."""
    by_cat: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_cat[it.category].append(it)
    embeds = []
    for cat, label in SECTIONS:
        rows = []
        for it in sorted(by_cat.get(cat, []), key=lambda i: -i.score):
            title = it.title.replace("[", "(").replace("]", ")")[:120]
            rows.append(f"• [{title}]({it.url}) — *{it.source}*")
        if not rows:
            continue
        desc = ""
        for row in rows:
            if len(desc) + len(row) + 1 > 3900:
                break
            desc += row + "\n"
        embeds.append({"title": label, "description": desc.strip(), "color": COLORS[cat]})
    if embeds:
        embeds[0]["author"] = {"name": f"Daily AI digest — {date_label}"}
    return embeds


def _post(webhook: str, payload: dict, client: httpx.Client) -> None:
    for attempt in range(5):
        r = client.post(webhook, json=payload)
        if r.status_code == 429:
            time.sleep(float(r.json().get("retry_after", 2)) + 0.25)
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return
    raise RuntimeError("Discord webhook: gave up after retries")


def send_embeds(webhook: str, embeds: list[dict], client: httpx.Client, content: str = "") -> None:
    for i in range(0, len(embeds), EMBEDS_PER_MESSAGE):
        payload = {"username": USERNAME, "embeds": embeds[i:i + EMBEDS_PER_MESSAGE],
                   "allowed_mentions": {"parse": []}}
        if content and i == 0:
            payload["content"] = content
        _post(webhook, payload, client)
        time.sleep(1)
