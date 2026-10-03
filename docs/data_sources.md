# Data sources

A source is only claimed as working after `scripts/probe_sources.py` passes against it.
Raw results of the latest run: `data/probe_results.json` (not committed; regenerate with `make probe`).

## Probe results — 2026-10-03, developer laptop (Windows 11, home network)

| Source | Type | Result | Detail | Decision |
|---|---|---|---|---|
| Google News RSS (US: `hl=en-US&gl=US`) | news | PASS | HTTP 200, 100 items, ~1 s | **Primary news** |
| Google News RSS (IN: `hl=en-IN&gl=IN`) | news | PASS | HTTP 200, 100 items, ~0.6 s | **Primary news (India issuers)** |
| Finnhub company-news | news | SKIP | `FINNHUB_API_KEY` not set | Optional; adapter skips cleanly without a key |
| GDELT DOC 2.0 | news | FAIL | HTTP 429 on two runs (~10–14 s responses) | Best-effort background only; skip on failure; re-probe before demo |
| StockTwits symbol stream | social | FAIL | HTTP 403 on two runs (blocked, likely Cloudflare) | Not used unless a later probe passes |
| Reddit RSS `r/stocks/new/.rss` | social | PASS | HTTP 200, 25 items | **Primary social** |
| Reddit RSS `r/investing/new/.rss` | social | FAIL | HTTP 429 on the second Reddit request, even with a 6 s gap | Reddit throttles unauthenticated RSS hard; the adapter must use a long per-source interval and rotate subreddits across cycles |

Result: requirement R2 (at least one news and one social source) is met by Google News + Reddit RSS.
The social source is unofficial and best-effort; REPLAY mode (cached real captures) is the fallback.

## Excluded by design

- **X/Twitter API** — no free tier since Feb 2026.
- **Yahoo Finance RSS** — reported HTTP 429s since Sep 2026.
- **Reddit OAuth API** — requires app approval; we use only public subreddit RSS.

## Constraints we honour

- Google News items are headline + publisher + timestamp only (no body); links are Google redirects and are not decoded.
- Descriptive `User-Agent` on every request; timeouts ≤10 s (GDELT ≤20 s); at most 2 retries; GDELT bodies are validated as JSON before parsing.
