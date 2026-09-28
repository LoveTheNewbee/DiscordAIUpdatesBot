# AI Radar

A free, serverless bot that keeps a Discord channel up to date on AI news and model releases.
No LLM, no API keys, no hosting: a GitHub Actions cron job fetches feeds and posts through a Discord webhook.

- **Realtime (every ~30 min):** new posts from labs (OpenAI, Anthropic, DeepMind, Mistral, xAI, Qwen, Google AI) and new x.y.0 releases of vLLM / Ollama / Transformers, each posted as its own embed.
- **Daily digest (12:00 UTC):** one message grouped into Labs / Releases / Hugging Face / News / Community / Papers, ranked by a simple score (source tier, launch keywords, model names, HN points, HF likes/upvotes, freshness).

## Setup

1. **Webhook:** Discord channel → Edit Channel → Integrations → Webhooks → New Webhook → Copy URL. Treat it as a secret.
2. **Repo:** `git init`, commit, create a GitHub repo, push. (Public repos get unlimited free Actions minutes.)
3. **Secret:** repo → Settings → Secrets and variables → Actions → New secret `DISCORD_WEBHOOK_URL`.
4. **Seed:** Actions tab → *AI Radar* → Run workflow → mode `seed`. This records what already exists so the channel isn't flooded. (First scheduled runs also self-seed.)
5. Done. Use *Run workflow* with mode `realtime` or `digest` to trigger manually.

## Local use

```bash
pip install -r requirements.txt
python -m ai_digest realtime --dry-run     # show what would be posted, change nothing
python -m ai_digest digest --dry-run
pytest
```

To post locally set `DISCORD_WEBHOOK_URL` first (drop `--dry-run`).

## Tuning

Everything lives in `sources.yaml`: add/remove feeds, change tiers, `filter: ai|release`, `exclude_title` regexes,
digest caps per section, keyword lists, freshness window. The digest time is the cron line in `.github/workflows/run.yml`
(keep the `github.event.schedule` string in the "Pick mode" step in sync if you change it).

## Notes

- `state/seen.json` is committed by the workflow after each run; it also keeps the repo "active" so GitHub doesn't pause the schedule.
- Anthropic and xAI don't publish RSS feeds, so they use the community-maintained mirror at `Olshansk/rss-feeds`.
- GitHub cron can lag several minutes under load; "every 30 min" is best-effort.
- A failing source is logged and skipped; the run only fails if *every* source fails (so you get GitHub's failure email).
