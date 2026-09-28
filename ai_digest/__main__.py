"""Entrypoint.

    python -m ai_digest realtime [--dry-run] [--seed]   # tier-1 sources, post new items now
    python -m ai_digest digest   [--dry-run] [--seed]   # tier-2/3 sources, one daily summary
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

from . import webhook
from .config import Config, load_config
from .dedupe import dedupe
from .models import Item
from .score import compute_score, passes_filter
from .sources import fetch_source
from .state import State


def collect(cfg: Config, mode: str, client: httpx.Client) -> tuple[list[Item], list[str]]:
    """Fetch every source for this mode. Returns (filtered+scored items, error messages)."""
    st = cfg.settings
    sources = [s for s in cfg.sources if (s["tier"] == 1) == (mode == "realtime")]
    now = datetime.now(timezone.utc)
    items: list[Item] = []
    errors: list[str] = []

    def run(src):
        try:
            return src, fetch_source(src, st, client), None
        except Exception as e:  # one bad source must never sink the run
            return src, [], f"{src['name']}: {type(e).__name__}: {e}"

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for src, fetched, err in ex.map(run, sources):
            if err:
                errors.append(err)
                continue
            max_age = timedelta(days=src.get("max_age_days", st["max_age_days"]))
            kept = 0
            for it in fetched:
                if now - it.published > max_age or it.published > now + timedelta(hours=1):
                    continue
                if not passes_filter(it, src, cfg):
                    continue
                it.score = compute_score(it, cfg, now)
                items.append(it)
                kept += 1
            print(f"  {src['name']:<22} fetched={len(fetched):<3} kept={kept}", file=sys.stderr)
    return dedupe(items), errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ai_digest")
    ap.add_argument("mode", choices=["realtime", "digest", "test"])
    ap.add_argument("--dry-run", action="store_true", help="print what would be posted; change nothing")
    ap.add_argument("--seed", action="store_true", help="mark everything current as seen, post nothing")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    cfg = load_config()
    st = cfg.settings
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not hook and not args.dry_run and not args.seed:
        print("DISCORD_WEBHOOK_URL is not set", file=sys.stderr)
        return 2

    if args.mode == "test":
        with httpx.Client(timeout=st["http_timeout"]) as client:
            webhook.send_embeds(hook, [{
                "title": "AI Radar is connected ✅",
                "description": "Webhook works. New AI news and releases will show up here.",
                "color": webhook.COLORS["release"]}], client)
        print("test message sent", file=sys.stderr)
        return 0

    state = State.load()
    headers = {"User-Agent": st["user_agent"]}
    with httpx.Client(timeout=st["http_timeout"], follow_redirects=True, headers=headers) as client:
        print(f"[{args.mode}] fetching…", file=sys.stderr)
        items, errors = collect(cfg, args.mode, client)
        for e in errors:
            print(f"  ! {e}", file=sys.stderr)
        if errors and len(errors) == len([s for s in cfg.sources if (s["tier"] == 1) == (args.mode == "realtime")]):
            print("every source failed", file=sys.stderr)
            return 1

        fresh = [i for i in items if i.id not in state.seen]

        # First run for a mode: record what already exists so the channel isn't flooded.
        if not args.dry_run and (args.seed or args.mode not in state.seeded):
            state.mark(i.id for i in items)
            state.seeded.add(args.mode)
            state.prune(st["seen_ttl_days"])
            state.save()
            print(f"seeded {len(items)} existing items; nothing posted", file=sys.stderr)
            return 0

        if args.mode == "realtime":
            to_post = sorted(fresh, key=lambda i: i.published)[: st["max_posts_per_run"]]
            embeds = [webhook.item_embed(i) for i in to_post]
            marked = to_post
        else:
            caps = st["digest_caps"]
            counts: dict[str, int] = {}
            to_post = []
            for it in sorted(fresh, key=lambda i: -i.score):
                if counts.get(it.category, 0) < caps.get(it.category, 5):
                    counts[it.category] = counts.get(it.category, 0) + 1
                    to_post.append(it)
            label = datetime.now(timezone.utc).strftime("%a %d %b")
            embeds = webhook.digest_embeds(to_post, label)
            marked = fresh  # everything considered today is retired, even if it missed the cut

        print(f"{len(fresh)} new, posting {len(to_post)}", file=sys.stderr)
        if args.dry_run:
            for i in to_post:
                print(f"[T{i.tier}|{i.category}|{i.score}] {i.source}: {i.title}\n    {i.url}")
            return 0
        if embeds:
            webhook.send_embeds(hook, embeds, client)
        state.mark(i.id for i in marked)
        state.prune(st["seen_ttl_days"])
        state.save()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
