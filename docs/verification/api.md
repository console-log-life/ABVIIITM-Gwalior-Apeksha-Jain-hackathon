# API verification (2026-10-07 16:20)

`python src/scripts/verify_api.py --live`: **87/87 checks passed**. Own API on a throw-away database with the REAL history loaded.

| result | method | request | status | note |
|---|---|---|---|---|
| PASS | GET | `/health` | 200 | expect 200 |
| PASS | GET | `/docs` | 200 | Swagger UI |
| PASS | GET | `/openapi.json` | 200 | expect 200 |
| PASS | GET | `/methodology` | 200 | expect 200 |
| PASS | GET | `/nope` | 404 | unknown route |
| PASS |  | `REAL history loaded` |  | {'signals': 1325, 'stress_runs': 54} event 2010-12-01T08:00:00+00:00 .. 2026-10-05T20:03:45+00:00 |
| PASS | GET | `/history` | 200 | expect 200 |
| PASS | POST | `/history/load` | 200 | fresh cache: reload only |
| PASS | POST | `/history/load?rebuild=maybe` | 422 | bad boolean |
| PASS | GET | `/overview?as_of=2026-10-05T20%3A03%3A45%2B00%3A00&hours=24` | 200 | expect 200 |
| PASS | GET | `/overview?hours=0` | 422 | hours < 1 |
| PASS | GET | `/overview?as_of=yesterday-ish` | 422 | bad timestamp |
| PASS | GET | `/signals?limit=5` | 200 | expect 200 |
| PASS |  | `GET /signals returns rows` |  | 5 rows |
| PASS | GET | `/signals?as_of=2026-10-05T20%3A03%3A45%2B00%3A00&hours=24&min_impact=5` | 200 | expect 200 |
| PASS | GET | `/signals?provenance=CACHED_REAL&event_type=Credit+Event` | 200 | expect 200 |
| PASS | GET | `/signals?event_type=Weather` | 422 | unknown event type |
| PASS | GET | `/signals?min_impact=11` | 422 | min_impact > 10 |
| PASS | GET | `/signals?provenance=MADE_UP` | 422 | unknown provenance |
| PASS | GET | `/signals?hours=1000` | 422 | hours > 720 |
| PASS | GET | `/signals?since_id=nope` | 404 | unknown since_id |
| PASS | GET | `/signals?since_id=77ddaafa-490c-411b-a694-1cff613f9354` | 200 | expect 200 |
| PASS | GET | `/signals/by-id/f76c6b11-dc46-476c-afe8-6b72f3cbbd75` | 200 | expect 200 |
| PASS | GET | `/signals/by-id/does-not-exist` | 404 | expect 404 |
| PASS | GET | `/signals/JPM?limit=5` | 200 | expect 200 |
| PASS |  | `GET /signals/JPM aggregates` |  | 5 |
| PASS | GET | `/signals/ZZZZ` | 200 | unknown ticker: empty aggregate |
| PASS | GET | `/signals/export.jsonl?min_impact=7` | 200 | expect 200 |
| PASS |  | `JSONL export: one JSON object per line` |  | 188 lines, content-type application/x-ndjson |
| PASS | GET | `/signals/export.jsonl?min_impact=0` | 422 | min_impact < 1 |
| PASS | GET | `/signals/stream?replay_last=2&max_events=2` | 200 | SSE |
| PASS |  | `SSE: text/event-stream with 2 signal events` |  | 2 events |
| PASS | GET | `/signals/stream?max_events=0` | 422 | max_events < 1 |
| PASS | POST | `/analyze {"text": "Moody's downgrades Reliance Industries as SEBI opens probe i` | 200 | expect 200 |
| PASS | POST | `/analyze {"text": "Moody's downgrades Reliance Industries as SEBI opens probe i` | 200 | same text again |
| PASS |  | `POST /analyze dedups (X-Duplicate)` |  | Regulatory impact 7.9 |
| PASS | POST | `/analyze {}` | 422 | missing text |
| PASS | POST | `/analyze {"text": ""}` | 422 | empty text |
| PASS | POST | `/analyze` | 422 | not JSON |
| PASS | POST | `/analyze/batch {"items": [{"text": "Fed cuts rates as inflation cools"}, {"text": "HD` | 200 | expect 200 |
| PASS | POST | `/analyze/batch {"items": []}` | 422 | empty batch |
| PASS | POST | `/analyze/batch {"items": [{"text": "a b c"}, {"text": "a b c"}, {"text": "a b c"}, {"` | 422 | 101 items |
| PASS | GET | `/portfolio` | 200 | expect 200 |
| PASS | GET | `/portfolio/scenarios` | 200 | expect 200 |
| PASS | POST | `/portfolio/stress-test {"scenario": "geopolitical_severe"}` | 200 | expect 200 |
| PASS | POST | `/portfolio/stress-test {"scenario": "idiosyncratic_credit", "issuer_id": "IN-TATAMOTORS"}` | 200 | expect 200 |
| PASS | POST | `/portfolio/stress-test {"custom": {"hy_spread_bp": 250, "equity_pct": -0.1}}` | 200 | expect 200 |
| PASS | POST | `/portfolio/stress-test {"scenario": "nope"}` | 422 | unknown scenario |
| PASS | POST | `/portfolio/stress-test {}` | 422 | neither scenario nor custom |
| PASS | GET | `/portfolio/stress-test` | 200 | latest run |
| PASS | GET | `/portfolio/stress-test?as_of=2000-01-01T00%3A00%3A00Z` | 404 | no run before 2000 |
| PASS | GET | `/stress-runs?limit=5` | 200 | expect 200 |
| PASS | GET | `/stress-runs/f5733ec0-1f13-4bd5-9395-9d8cd8509f82` | 200 | expect 200 |
| PASS | GET | `/stress-runs/nope` | 404 | expect 404 |
| PASS | POST | `/portfolio/what-if {"shocks": {"hy_spread_bp": 300}}` | 200 | expect 200 |
| PASS | POST | `/portfolio/what-if {"shocks": {"equity_pct": -5}}` | 422 | equity_pct out of range |
| PASS | POST | `/portfolio/what-if {"shocks": {}, "issuer_id": "XX-NOPE"}` | 422 | issuer not held |
| PASS | POST | `/portfolio/what-if {}` | 422 | missing shocks |
| PASS | GET | `/watchlist?as_of=2026-10-05T20%3A03%3A45%2B00%3A00&hours=24` | 200 | expect 200 |
| PASS | GET | `/watchlist?hours=0` | 422 | hours < 1 |
| PASS | GET | `/propagation?issuer_id=IN-TATAMOTORS&as_of=2026-10-05T20%3A03%3A45%2B00%3A00` | 200 | expect 200 |
| PASS | GET | `/propagation?issuer_id=XX-NOPE` | 404 | issuer not held |
| PASS | GET | `/propagation` | 422 | issuer_id missing |
| PASS | GET | `/credit-brief/IN-TATAMOTORS?format=json` | 200 | expect 200 |
| PASS | GET | `/credit-brief/IN-TATAMOTORS?format=html` | 200 | expect 200 |
| PASS | GET | `/credit-brief/IN-TATAMOTORS?format=pdf` | 200 | expect 200 |
| PASS |  | `credit brief PDF is a PDF` |  | 2582 bytes |
| PASS | GET | `/credit-brief/XX-NOPE` | 404 | expect 404 |
| PASS | GET | `/credit-brief/IN-TATAMOTORS?format=docx` | 422 | format docx |
| PASS | GET | `/demo/status` | 200 | expect 200 |
| PASS | POST | `/demo/start {"mode": "LIVE"}` | 422 | LIVE goes through /mode |
| PASS | POST | `/demo/start {"mode": "FOO"}` | 422 | unknown mode |
| PASS | POST | `/demo/start {"mode": "SCENARIO", "step_seconds": 500}` | 422 | step_seconds > 120 |
| PASS | POST | `/demo/start {"mode": "SCENARIO", "step_seconds": 0}` | 200 | expect 200 |
| PASS |  | `scenario demo triggered stress runs` |  | 58 -> 61, RAG GREEN -> AMBER -> RED |
| PASS |  | `Tata Motors on the watchlist after the story` |  | WATCH-NEGATIVE |
| PASS | POST | `/mode {}` | 422 | missing mode |
| PASS | POST | `/mode {"mode": "FOO"}` | 422 | unknown mode |
| PASS | POST | `/mode {"mode": "REPLAY"}` | 200 | REPLAY |
| PASS | POST | `/mode {"mode": "LIVE"}` | 200 | LIVE (real network) |
| PASS |  | `LIVE ingestion running` |  |  |
| PASS | GET | `/health` | 200 | health during LIVE |
| PASS | POST | `/mode {"mode": "SCENARIO"}` | 200 | back to SCENARIO stops LIVE |
| PASS | POST | `/demo/reset` | 200 | expect 200 |
| PASS | GET | `/health` | 200 | after reset |
| PASS |  | `server log has no errors or tracebacks` |  | 0 bad lines |
| PASS |  | `no 5xx responses in the access log` |  | 126 requests logged |
