"""Probe every candidate data source on THIS machine and print a PASS/FAIL table.

A source may only be claimed as working in docs/README after it PASSes here.
Results are also written to data/probe_results.json (timestamped) for docs/data_sources.md.

Usage:  python src/scripts/probe_sources.py [--symbol AAPL]
Exit code 0 if at least one news AND one social source pass, else 1.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import feedparser  # noqa: E402
import httpx  # noqa: E402

from app.config import get_settings  # noqa: E402


@dataclass
class ProbeResult:
    source: str
    source_type: str
    status: str  # PASS | FAIL | SKIP
    http_status: int | None
    items: int
    latency_s: float
    note: str
    sample_title: str = ""


def _get(client: httpx.Client, url: str, timeout: float) -> tuple[httpx.Response | None, float, str]:
    t0 = time.perf_counter()
    try:
        r = client.get(url, timeout=timeout, follow_redirects=True)
        return r, time.perf_counter() - t0, ""
    except httpx.HTTPError as exc:
        return None, time.perf_counter() - t0, f"{type(exc).__name__}: {exc}"[:160]


def probe_rss(client: httpx.Client, name: str, source_type: str, url: str, timeout: float) -> ProbeResult:
    r, dt, err = _get(client, url, timeout)
    if r is None:
        return ProbeResult(name, source_type, "FAIL", None, 0, dt, err)
    if r.status_code != 200:
        return ProbeResult(name, source_type, "FAIL", r.status_code, 0, dt, f"HTTP {r.status_code}")
    feed = feedparser.parse(r.content)
    n = len(feed.entries)
    if n == 0:
        note = "no entries" + (f" (bozo: {feed.bozo_exception})" if feed.bozo else "")
        return ProbeResult(name, source_type, "FAIL", 200, 0, dt, note[:160])
    return ProbeResult(name, source_type, "PASS", 200, n, dt, "ok", feed.entries[0].get("title", "")[:90])


def probe_google_news(client: httpx.Client, timeout: float, region: str) -> ProbeResult:
    q = quote_plus("Apple stock" if region == "US" else "Reliance Industries shares")
    params = "hl=en-US&gl=US&ceid=US:en" if region == "US" else "hl=en-IN&gl=IN&ceid=IN:en"
    url = f"https://news.google.com/rss/search?q={q}&{params}"
    return probe_rss(client, f"google_news[{region}]", "news", url, timeout)


def probe_finnhub(client: httpx.Client, timeout: float, symbol: str, key: str) -> ProbeResult:
    if not key:
        return ProbeResult("finnhub", "news", "SKIP", None, 0, 0.0, "FINNHUB_API_KEY not set (optional)")
    today = datetime.now(UTC).date()
    url = (
        f"https://finnhub.io/api/v1/company-news?symbol={symbol}"
        f"&from={today - timedelta(days=3)}&to={today}&token={key}"
    )
    r, dt, err = _get(client, url, timeout)
    if r is None:
        return ProbeResult("finnhub", "news", "FAIL", None, 0, dt, err.replace(key, "***"))
    if r.status_code != 200:
        return ProbeResult("finnhub", "news", "FAIL", r.status_code, 0, dt, f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        return ProbeResult("finnhub", "news", "FAIL", 200, 0, dt, "non-JSON body")
    if not isinstance(data, list):
        return ProbeResult("finnhub", "news", "FAIL", 200, 0, dt, f"unexpected payload: {str(data)[:80]}")
    title = data[0].get("headline", "") if data else ""
    status = "PASS" if data else "FAIL"
    note = "ok" if data else "empty list"
    return ProbeResult("finnhub", "news", status, 200, len(data), dt, note, title[:90])


def probe_gdelt(client: httpx.Client, timeout: float) -> ProbeResult:
    q = quote_plus('(sanctions OR "central bank" OR tariff) sourcelang:english')
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={q}&mode=artlist&format=json&maxrecords=50"
    r, dt, err = _get(client, url, timeout)
    if r is None:
        return ProbeResult("gdelt", "news", "FAIL", None, 0, dt, err)
    if r.status_code != 200:
        return ProbeResult("gdelt", "news", "FAIL", r.status_code, 0, dt, f"HTTP {r.status_code}")
    # GDELT may return a plain-text error with HTTP 200 — validate JSON before trusting it.
    try:
        data = r.json()
    except ValueError:
        return ProbeResult("gdelt", "news", "FAIL", 200, 0, dt, f"non-JSON body: {r.text[:100]!r}")
    arts = data.get("articles", []) if isinstance(data, dict) else []
    if not arts:
        return ProbeResult("gdelt", "news", "FAIL", 200, 0, dt, "JSON ok but no articles")
    return ProbeResult("gdelt", "news", "PASS", 200, len(arts), dt, "ok", arts[0].get("title", "")[:90])


def probe_stocktwits(client: httpx.Client, timeout: float, symbol: str) -> ProbeResult:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
    r, dt, err = _get(client, url, timeout)
    if r is None:
        return ProbeResult("stocktwits", "social", "FAIL", None, 0, dt, err)
    if r.status_code != 200:
        return ProbeResult("stocktwits", "social", "FAIL", r.status_code, 0, dt,
                           f"HTTP {r.status_code} (likely blocked/Cloudflare)")
    try:
        msgs = r.json().get("messages", [])
    except (ValueError, AttributeError):
        return ProbeResult("stocktwits", "social", "FAIL", 200, 0, dt, f"non-JSON body: {r.text[:80]!r}")
    if not msgs:
        return ProbeResult("stocktwits", "social", "FAIL", 200, 0, dt, "no messages")
    tagged = sum(1 for m in msgs if ((m.get("entities") or {}).get("sentiment") or {}).get("basic"))
    return ProbeResult("stocktwits", "social", "PASS", 200, len(msgs), dt,
                       f"{tagged} with Bullish/Bearish tag", (msgs[0].get("body") or "")[:90])


def probe_bluesky(client: httpx.Client, timeout: float, handle: str, app_password: str) -> ProbeResult:
    if not (handle and app_password):
        return ProbeResult("bluesky", "social", "SKIP", None, 0, 0.0,
                           "BLUESKY_HANDLE / BLUESKY_APP_PASSWORD not set (optional)")
    t0 = time.perf_counter()
    try:
        r = client.post("https://bsky.social/xrpc/com.atproto.server.createSession",
                        json={"identifier": handle, "password": app_password}, timeout=timeout)
    except httpx.HTTPError as exc:
        return ProbeResult("bluesky", "social", "FAIL", None, 0, time.perf_counter() - t0,
                           f"createSession {type(exc).__name__}")
    if r.status_code != 200:
        return ProbeResult("bluesky", "social", "FAIL", r.status_code, 0, time.perf_counter() - t0,
                           f"createSession HTTP {r.status_code}: {r.text[:80]}")
    jwt = r.json().get("accessJwt", "")
    url = "https://bsky.social/xrpc/app.bsky.feed.searchPosts?q=%24AAPL&limit=25&sort=latest"
    try:
        r = client.get(url, headers={"Authorization": f"Bearer {jwt}"}, timeout=timeout)
    except httpx.HTTPError as exc:
        return ProbeResult("bluesky", "social", "FAIL", None, 0, time.perf_counter() - t0,
                           f"searchPosts {type(exc).__name__}")
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        return ProbeResult("bluesky", "social", "FAIL", r.status_code, 0, dt, f"searchPosts HTTP {r.status_code}")
    posts = r.json().get("posts", [])
    if not posts:
        return ProbeResult("bluesky", "social", "FAIL", 200, 0, dt, "authenticated, but no posts")
    text = ((posts[0].get("record") or {}).get("text") or "")[:90]
    return ProbeResult("bluesky", "social", "PASS", 200, len(posts), dt, "authenticated searchPosts ok", text)


def probe_mastodon(client: httpx.Client, timeout: float, instance: str, tag: str) -> ProbeResult:
    name = f"mastodon[{instance.split('.')[0]}#{tag}]"
    r, dt, err = _get(client, f"https://{instance}/api/v1/timelines/tag/{tag}?limit=40", timeout)
    if r is None:
        return ProbeResult(name, "social", "FAIL", None, 0, dt, err)
    if r.status_code != 200:
        return ProbeResult(name, "social", "FAIL", r.status_code, 0, dt, f"HTTP {r.status_code}: {r.text[:60]}")
    try:
        statuses = r.json()
    except ValueError:
        return ProbeResult(name, "social", "FAIL", 200, 0, dt, "non-JSON body")
    if not isinstance(statuses, list) or not statuses:
        return ProbeResult(name, "social", "FAIL", 200, 0, dt, "no statuses")
    newest = statuses[0].get("created_at", "?")
    return ProbeResult(name, "social", "PASS", 200, len(statuses), dt, f"newest {newest}",
                       re.sub(r"<[^>]+>", " ", statuses[0].get("content", ""))[:90].strip())


def run(symbol: str, reddit_sub: str) -> list[ProbeResult]:
    s = get_settings()
    headers = {"User-Agent": s.user_agent, "Accept": "*/*"}
    results: list[ProbeResult] = []
    with httpx.Client(headers=headers) as client:
        results.append(probe_google_news(client, s.http_timeout_s, "US"))
        results.append(probe_google_news(client, s.http_timeout_s, "IN"))
        results.append(probe_finnhub(client, s.http_timeout_s, symbol, s.finnhub_api_key.strip()))
        results.append(probe_gdelt(client, s.gdelt_timeout_s))
        results.append(probe_stocktwits(client, s.http_timeout_s, symbol))
        # One subreddit per run: Reddit returns 429 on back-to-back unauthenticated requests.
        results.append(probe_rss(client, f"reddit[r/{reddit_sub}]", "social",
                                 f"https://www.reddit.com/r/{reddit_sub}/new/.rss", s.http_timeout_s))
        results.append(probe_bluesky(client, s.http_timeout_s, s.bluesky_handle.strip(),
                                     s.bluesky_app_password.strip()))
        for tag in ("stocks", "investing"):
            results.append(probe_mastodon(client, s.http_timeout_s, "mastodon.social", tag))
    return results


def print_table(results: list[ProbeResult]) -> None:
    hdr = f"{'SOURCE':<28} {'TYPE':<7} {'STATUS':<6} {'HTTP':<5} {'ITEMS':>5} {'SECS':>6}  NOTE"
    print(hdr)
    print("-" * len(hdr) + "-" * 30)
    for r in results:
        print(f"{r.source:<28} {r.source_type:<7} {r.status:<6} {str(r.http_status or '-'):<5} "
              f"{r.items:>5} {r.latency_s:>6.2f}  {r.note}")
        if r.sample_title:
            print(f"{'':<28} sample: {r.sample_title}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles default to cp1252
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--reddit-sub", default="stocks")
    args = ap.parse_args()

    results = run(args.symbol, args.reddit_sub)
    print_table(results)

    out = get_settings().resolve(Path("data/probe_results.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"probed_at": datetime.now(UTC).isoformat(),
                               "results": [asdict(r) for r in results]}, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")

    news_ok = any(r.status == "PASS" and r.source_type == "news" for r in results)
    social_ok = any(r.status == "PASS" and r.source_type == "social" for r in results)
    print(f"news source available: {news_ok} | social source available: {social_ok}")
    return 0 if (news_ok and social_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
