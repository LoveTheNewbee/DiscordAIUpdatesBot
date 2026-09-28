from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|ref$|ref_src|source$|mc_)", re.I)
_WS = re.compile(r"\s+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is", "are", "at", "by", "from", "new"}


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)])
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower() or "https", host, path, "", query, ""))


def item_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def clean_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = BeautifulSoup(raw, "html.parser").get_text(" ")
    return _WS.sub(" ", html.unescape(text)).strip()


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    return cut + "…"


def title_tokens(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9.]+", title.lower())
    return frozenset(w for w in words if w not in _STOP and len(w) > 1)


def first_image(raw_html: str | None) -> str | None:
    if not raw_html:
        return None
    img = BeautifulSoup(raw_html, "html.parser").find("img")
    src = img.get("src") if img else None
    return src if src and src.startswith("http") else None
