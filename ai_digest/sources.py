"""Fetchers. Each takes (source_cfg, settings, httpx.Client) and returns list[Item]."""
from __future__ import annotations

import calendar
import re
import time
from datetime import datetime, timezone

import feedparser
import httpx

from .models import Item
from .text import clean_html, first_image, item_id, truncate

_PRERELEASE = re.compile(r"(rc|alpha|beta|dev|nightly|pre|preview|snapshot)[\d.\-]*", re.I)
_MINOR = re.compile(r"^v?\d+\.\d+\.0$")


def _make(src: dict, st: dict, *, title: str, url: str, published: datetime, summary: str = "",
          image: str | None = None, popularity: float = 0.0) -> Item:
    return Item(
        id=item_id(url), title=title, url=url, source=src["name"], tier=src["tier"],
        category=src["category"], published=published,
        summary=truncate(summary, st["summary_chars"]), image=image, popularity=popularity,
    )


def _iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _entry_date(e) -> datetime:
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _entry_html(e) -> str:
    if e.get("content"):
        return e["content"][0].get("value", "")
    return e.get("summary", "") or ""


def _entry_image(e) -> str | None:
    for key in ("media_thumbnail", "media_content"):
        for m in e.get(key, []) or []:
            if m.get("url", "").startswith("http") and m.get("medium", "image") == "image":
                return m["url"]
    for enc in e.get("enclosures", []) or []:
        if enc.get("type", "").startswith("image") and enc.get("href", "").startswith("http"):
            return enc["href"]
    return first_image(_entry_html(e))


def fetch_rss(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    r = client.get(src["url"])
    r.raise_for_status()
    entries = sorted(feedparser.parse(r.content).entries, key=_entry_date, reverse=True)
    items = []
    for e in entries[: src.get("limit", 30)]:
        url, title = e.get("link"), clean_html(e.get("title"))
        if not url or not title:
            continue
        summary = "" if src.get("summary") is False else clean_html(_entry_html(e))
        items.append(_make(src, st, title=title, url=url, published=_entry_date(e),
                           summary=summary, image=_entry_image(e)))
    return items


def fetch_github_releases(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    r = client.get(f"https://github.com/{src['repo']}/releases.atom")
    r.raise_for_status()
    items = []
    for e in feedparser.parse(r.content).entries[:20]:
        url = e.get("link", "")
        tag = url.rsplit("/tag/", 1)[-1] if "/tag/" in url else e.get("title", "")
        if _PRERELEASE.search(tag):
            continue
        if src.get("minor_only") and not _MINOR.match(tag):
            continue
        items.append(_make(src, st, title=f"{src['name']} {tag} released", url=url,
                           published=_entry_date(e), summary=clean_html(_entry_html(e))))
    return items


def fetch_hn(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    since = int(time.time() - src.get("window_hours", 24) * 3600)
    found: dict[str, Item] = {}
    for q in src["queries"]:
        r = client.get("https://hn.algolia.com/api/v1/search_by_date", params={
            "tags": "story", "query": q, "hitsPerPage": 20,
            "numericFilters": f"points>={src['min_points']},created_at_i>{since}"})
        r.raise_for_status()
        for h in r.json().get("hits", []):
            title = h.get("title")
            if not title:
                continue
            hn_url = f"https://news.ycombinator.com/item?id={h['objectID']}"
            pts = h.get("points") or 0
            item = _make(
                src, st, title=title, url=h.get("url") or hn_url,
                published=datetime.fromtimestamp(h["created_at_i"], tz=timezone.utc),
                summary=f"{pts} points · {h.get('num_comments', 0)} comments · discussion: {hn_url}",
                popularity=min(30.0, pts / 20))
            found[item.id] = item
    return list(found.values())


def fetch_hf_models(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    r = client.get("https://huggingface.co/api/models", params={
        "sort": "trendingScore", "direction": -1, "limit": src.get("limit", 40)})
    r.raise_for_status()
    items = []
    for m in r.json():
        likes = m.get("likes", 0)
        if likes < src.get("min_likes", 100) or not m.get("createdAt"):
            continue
        kind = m.get("pipeline_tag") or "model"
        items.append(_make(
            src, st, title=f"{m['id']} is trending on Hugging Face",
            url=f"https://huggingface.co/{m['id']}", published=_iso(m["createdAt"]),
            summary=f"{kind} · ♥ {likes:,} · {m.get('downloads', 0):,} downloads",
            popularity=min(30.0, likes / 100)))
    return items


def fetch_hf_papers(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    r = client.get("https://huggingface.co/api/daily_papers", params={"limit": src.get("limit", 30)})
    r.raise_for_status()
    items = []
    for d in r.json():
        p = d.get("paper", {})
        ups = p.get("upvotes", 0)
        if ups < src.get("min_upvotes", 10) or not p.get("id"):
            continue
        when = d.get("submittedOnDailyAt") or p.get("publishedAt") or datetime.now(timezone.utc).isoformat()
        items.append(_make(
            src, st, title=d.get("title") or p.get("title", ""),
            url=f"https://huggingface.co/papers/{p['id']}", published=_iso(when),
            summary=clean_html(p.get("summary") or d.get("summary")), popularity=min(30.0, ups / 3)))
    return items


FETCHERS = {
    "rss": fetch_rss,
    "github_releases": fetch_github_releases,
    "hn": fetch_hn,
    "hf_models": fetch_hf_models,
    "hf_papers": fetch_hf_papers,
}


def fetch_source(src: dict, st: dict, client: httpx.Client) -> list[Item]:
    return FETCHERS[src["type"]](src, st, client)
