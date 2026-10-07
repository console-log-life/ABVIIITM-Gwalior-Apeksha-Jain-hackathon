# Data sources

A source is only claimed as working after `src/scripts/probe_sources.py` passes against it.
Raw results of the latest run: `data/probe_results.json` (not committed; regenerate with `tasks.ps1 probe`).
Per-source settings (queries, intervals, rate limits, backoffs): `src/risk_engine/ingestion/sources.yaml`.

## Probe and capture results — 2026-10-03, developer laptop (Windows 11, home network)

| Source | Type | Probe result | Live capture (same evening) | Status in the system |
|---|---|---|---|---|
| Google News RSS (US + IN editions) | news | PASS — HTTP 200, 100 items/query | 581 new headlines from 15 queries | **Primary news** |
| GDELT DOC 2.0 | news | FAIL — HTTP 429 on 3 probes | 1 of 3 runs succeeded (50 articles, 44 new); next run 429 | Best-effort; 30 min backoff on 429 |
| Finnhub company-news | news | SKIP — no `FINNHUB_API_KEY` | — | Optional; adapter skips cleanly without a key |
| Reddit RSS (`/r/{sub}/new/.rss`) | social | PASS for r/stocks; 429 when a second request followed within ~60 s | 25 posts per run | **Primary social**, rate-limited (see below) |
| Mastodon hashtag timelines (mastodon.social `#stocks #investing #finance #markets`) | social | PASS — HTTP 200, 40 statuses per tag | 76 + 53 new posts in two runs | **Social** (added in M1 after passing the probe) |
| Bluesky `app.bsky.feed.searchPosts` (authenticated) | social | SKIP — `BLUESKY_HANDLE` / `BLUESKY_APP_PASSWORD` not set | — | Adapter built; activates when credentials are set. Not claimed as working until a probe PASSes |
| StockTwits symbol stream | social | FAIL — HTTP 403 on every attempt (blocked) | — | Best-effort; 1 h backoff on 403 |

### Re-probe — 2026-10-03 ~19:00 UTC (M7, before writing the README)

| Source | Result |
|---|---|
| Google News US / IN | PASS (100 / 100 items) |
| Reddit `r/investing` | PASS (25 items) |
| Mastodon `#stocks` / `#investing` | PASS (40 / 40) |
| GDELT | FAIL HTTP 429 |
| StockTwits | FAIL HTTP 403 |
| Finnhub / Bluesky | SKIP (no keys) |

Result: requirement R2 (at least one news and one social source) is met by Google News plus Reddit RSS
and Mastodon. Both social sources are unofficial and best-effort; REPLAY mode (cached real captures) is the fallback.

## Reddit throttling policy

Reddit throttles unauthenticated RSS hard, and the probe confirmed it (429 on a second request within about 60 s). The adapter:

- polls **one subreddit per cycle**, rotating `stocks → investing → wallstreetbets → IndianStockMarket`;
- never sends two Reddit requests less than **120 s** apart (token bucket; if a cycle comes too soon it is
  skipped, not delayed, and the same subreddit is tried next time);
- parks Reddit for **15 min** after any HTTP 429.

Rotation position, last request time and backoffs are saved in `data/cache/state.json` between
`capture_cache.py` runs.

## Caching real data for REPLAY

`src/scripts/capture_cache.py` fetches every live source once and writes only new documents to
`data/cache/captures/capture_<UTC timestamp>.jsonl` with `provenance=CACHED_REAL` and the real `captured_at`.
That directory is **git-ignored**: it holds real social posts and is not published. The repository ships
`data/cache/sample/sample_google_news.jsonl` instead: 50 news headlines built by `src/scripts/build_cache_sample.py`.
REPLAY falls back to that sample when no local captures exist.
Documents are deduplicated against the whole existing cache (exact plus same-source near-duplicates).

## Excluded by design

- **X/Twitter API**: no free tier since Feb 2026.
- **Yahoo Finance RSS**: reported HTTP 429s since Sep 2026.
- **Reddit OAuth API**: requires app approval; we use only public subreddit RSS.

## Constraints we honour

- Google News items are headline + publisher + timestamp only (no body). Links are Google redirects and are not decoded.
- Descriptive `User-Agent` on every request. Timeouts are ≤10 s (GDELT ≤20 s), with at most 2 retries (transport errors and 5xx only).
- GDELT bodies are validated as JSON before parsing, because it can return plain-text errors with HTTP 200.
- API keys are sent in headers (Finnhub `X-Finnhub-Token`), never in URLs, so they cannot leak into logs.
- Bluesky uses an **app password**, never the account password. The session is reused and refreshed, not re-created each cycle.
