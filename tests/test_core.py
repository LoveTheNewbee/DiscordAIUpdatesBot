from datetime import datetime, timedelta, timezone

from ai_digest import webhook
from ai_digest.config import load_config
from ai_digest.dedupe import dedupe
from ai_digest.models import Item
from ai_digest.score import compute_score, passes_filter
from ai_digest.sources import fetch_github_releases, fetch_rss
from ai_digest.state import State
from ai_digest.text import canonical_url, clean_html, item_id, truncate

NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
CFG = load_config()
SETTINGS = {"summary_chars": 100}


def mk(title, url="https://x.com/a", tier=1, category="lab", published=NOW, **kw):
    return Item(id=item_id(url), title=title, url=url, source="S", tier=tier,
                category=category, published=published, **kw)


class FakeResp:
    def __init__(self, content):
        self.content = content.encode()

    def raise_for_status(self):
        pass


class FakeClient:
    def __init__(self, content):
        self.content = content

    def get(self, *a, **k):
        return FakeResp(self.content)


def test_canonical_url_strips_tracking_and_www():
    assert canonical_url("https://www.Example.com/a/?utm_source=x&id=2#frag") == "https://example.com/a?id=2"
    assert item_id("https://example.com/a/") == item_id("https://www.example.com/a?utm_campaign=z")


def test_clean_and_truncate():
    assert clean_html("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    out = truncate("word " * 100, 50)
    assert len(out) <= 50 and out.endswith("…")


def test_dedupe_keeps_highest_tier_for_same_story():
    a = mk("Anthropic releases Claude Sonnet 5.5 today", "https://a.com/1", tier=1)
    b = mk("Anthropic releases Claude Sonnet 5.5", "https://b.com/2", tier=2)
    c = mk("Something entirely different", "https://c.com/3", tier=2)
    kept = dedupe([b, c, a])
    assert {i.url for i in kept} == {"https://a.com/1", "https://c.com/3"}


def test_dedupe_same_url():
    assert len(dedupe([mk("A story", "https://a.com/1"), mk("A story v2", "https://www.a.com/1/")])) == 1


def test_scoring_prefers_launches_and_fresh_items():
    launch = mk("Introducing Claude Opus 5", published=NOW)
    plain = mk("Our approach to policy", published=NOW - timedelta(days=2))
    assert compute_score(launch, CFG, NOW) > compute_score(plain, CFG, NOW) + 30


def test_filters():
    src_ai, src_rel = {"filter": "ai"}, {"filter": "release"}
    assert passes_filter(mk("Sonnet 5.5"), src_ai, CFG)
    assert not passes_filter(mk("Don't couple your Go code to GitHub"), src_ai, CFG)
    assert passes_filter(mk("Introducing a thing"), src_rel, CFG)
    assert not passes_filter(mk("Company hires new CFO"), src_rel, CFG)
    assert not passes_filter(mk("Weekly recap"), {"exclude_title": ["recap"]}, CFG)


def test_rss_parsing():
    xml = """<rss version="2.0"><channel><title>t</title>
    <item><title>Hello &amp; welcome</title><link>https://a.com/1</link>
    <description>&lt;p&gt;Body &lt;img src="https://a.com/i.png"/&gt; text&lt;/p&gt;</description>
    <pubDate>Mon, 28 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
    src = {"name": "T", "tier": 1, "category": "lab", "url": "u"}
    [it] = fetch_rss(src, SETTINGS, FakeClient(xml))
    assert it.title == "Hello & welcome"
    assert it.summary == "Body text"
    assert it.image == "https://a.com/i.png"
    assert it.published == datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def test_github_releases_minor_only_and_prerelease_filter():
    def entry(tag):
        return (f'<entry><id>t:{tag}</id><title>{tag}</title>'
                f'<link href="https://github.com/o/r/releases/tag/{tag}"/>'
                f'<updated>2026-09-28T10:00:00Z</updated><content type="html">notes</content></entry>')
    xml = ('<feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>'
           + "".join(entry(t) for t in ["v1.2.0", "v1.2.1", "v1.3.0rc1", "v2.0.0"]) + "</feed>")
    src = {"name": "Repo", "tier": 1, "category": "release", "repo": "o/r", "minor_only": True}
    titles = [i.title for i in fetch_github_releases(src, SETTINGS, FakeClient(xml))]
    assert titles == ["Repo v1.2.0 released", "Repo v2.0.0 released"]


def test_item_embed_limits():
    it = mk("T" * 500, summary="s" * 2000, image="https://a.com/i.png")
    e = webhook.item_embed(it)
    assert len(e["title"]) <= 256 and len(e["description"]) <= 600
    assert e["thumbnail"]["url"] == "https://a.com/i.png"


def test_digest_embeds_grouped_and_within_limits():
    items = [mk(f"Story {n} [x]", f"https://a.com/{n}", tier=2, category=c, score=n)
             for n, c in enumerate(["news"] * 60 + ["paper"] * 5)]
    embeds = webhook.digest_embeds(items, "Mon 28 Sep")
    assert [e["title"] for e in embeds] == ["📰 News", "📄 Papers"]
    assert all(len(e["description"]) <= 4096 for e in embeds)
    assert embeds[0]["author"]["name"].startswith("Daily AI digest")
    assert "[x]" not in embeds[0]["description"]  # brackets would break masked links


def test_send_embeds_chunks_and_retries_on_429(monkeypatch):
    monkeypatch.setattr(webhook.time, "sleep", lambda s: None)
    calls = []

    class R:
        def __init__(self, code):
            self.status_code = code

        def json(self):
            return {"retry_after": 0.1}

        def raise_for_status(self):
            assert self.status_code < 400

    class C:
        def post(self, url, json):
            calls.append(json)
            return R(429 if len(calls) == 1 else 204)

    webhook.send_embeds("http://hook", [{"title": str(i)} for i in range(7)], C())
    assert len(calls) == 3  # 1 retry + 2 chunks (5 + 2)
    assert len(calls[1]["embeds"]) == 5 and len(calls[2]["embeds"]) == 2


def test_state_roundtrip_and_prune(tmp_path):
    p = tmp_path / "seen.json"
    s = State()
    s.mark(["old"], now=NOW - timedelta(days=60))
    s.mark(["new"], now=NOW)
    s.seeded.add("realtime")
    s.prune(45, now=NOW)
    s.save(p)
    loaded = State.load(p)
    assert set(loaded.seen) == {"new"} and loaded.seeded == {"realtime"}
