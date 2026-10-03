"""Render docs/submission/doselect_answer.md -> doselect_answer.html (only <h2> <h3> <p> <ul> <li> <strong> <a>)
and run the mechanical quality checks of spec section 16.4. Prints PASS/FAIL per item.

Usage:  python scripts/build_submission.py
Exit code 0 when every check passes (link placeholders are reported, and the answer is NOT ready to submit while any
remain).
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MD = ROOT / "docs" / "submission" / "doselect_answer.md"
HTML_OUT = ROOT / "docs" / "submission" / "doselect_answer.html"
PROBE = ROOT / "data" / "probe_results.json"
EVAL = ROOT / "data" / "eval" / "eval_results.json"
BENCH = ROOT / "data" / "eval" / "benchmark_results.json"
PLACEHOLDERS = ["[GITHUB REPOSITORY LINK]", "[LIVE DEMO LINK]", "[PRESENTATION LINK]"]
SECTIONS = ["Executive summary", "Solution overview", "Downstream module", "Technical architecture",
            "AI/NLP methodology", "Data sources", "Key features", "Results", "Business impact", "Limitations",
            "Future scope", "Deliverables"]
SOURCE_FAMILIES = {"google_news": "Google News", "reddit": "Reddit", "mastodon": "Mastodon", "gdelt": "GDELT",
                   "stocktwits": "StockTwits", "finnhub": "Finnhub", "bluesky": "Bluesky"}


# ------------------------------------------------------------------ markdown -> restricted HTML
def inline(text: str) -> str:
    out = html.escape(text, quote=False)
    out = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                 lambda m: f'<a href="{html.escape(m.group(2))}">{m.group(1)}</a>', out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return out


def render(md: str) -> str:
    parts, in_list, para = [], False, []

    def flush_para():
        if para:
            parts.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("- "):
            flush_para()
            if not in_list:
                parts.append("<ul>")
                in_list = True
            parts.append(f"<li>{inline(s[2:])}</li>")
            continue
        if in_list:
            parts.append("</ul>")
            in_list = False
        if not s:
            flush_para()
        elif s.startswith("### "):
            flush_para()
            parts.append(f"<h3>{inline(s[4:])}</h3>")
        elif s.startswith("## "):
            flush_para()
            parts.append(f"<h2>{inline(s[3:])}</h2>")
        else:
            para.append(s)
    flush_para()
    if in_list:
        parts.append("</ul>")
    return "\n".join(parts) + "\n"


def sections(md: str) -> dict[str, str]:
    out, cur = {}, None
    for line in md.splitlines():
        if line.startswith("### "):
            cur = line[4:].strip()
            out[cur] = ""
        elif cur:
            out[cur] += line + "\n"
    return out


def numbers_in(text: str) -> list[str]:
    return re.findall(r"(?<![\w.])\d+(?:\.\d+)?", text)


def allowed_numbers() -> set[str]:
    vals: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, int | float) and not isinstance(x, bool):
            vals.update({f"{x}", f"{x:g}", f"{float(x):.1f}", f"{float(x):.2f}", f"{float(x):.3f}"})

    for p in (EVAL, BENCH):
        walk(json.loads(p.read_text(encoding="utf-8")))
    from app.config import get_settings
    from portfolio.stress_engine import StressEngine

    eng = StressEngine(get_settings())
    for name, sc in eng.scenarios.items():
        held = sorted(set(eng.portfolio.df["issuer_id"]) - {""})
        summary, _ = eng.run(name, held[0] if sc.get("issuer_only") else None)
        vals.add(f"{summary['loss_pct']:.2f}")
    vals.update({str(len(eng.portfolio.df)), "1", "10"})
    return vals


# ------------------------------------------------------------------ checks
def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    md = MD.read_text(encoding="utf-8")
    out_html = render(md)
    HTML_OUT.write_text(out_html, encoding="utf-8")
    secs = sections(md)
    low = md.lower()
    checks: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # structure / format
    order = [s for s in secs if s in SECTIONS]
    check("All required sections present, in order", order == SECTIONS, f"found {order}")
    words = len(re.findall(r"\b\w[\w'’-]*\b", md))
    check("Length 700–1,100 words", 700 <= words <= 1100, f"{words} words")
    exec_words = len(re.findall(r"\b\w[\w'’-]*\b", secs.get("Executive summary", "")))
    check("Executive summary ≤ 80 words", exec_words <= 80, f"{exec_words} words")
    feats = [x for x in secs.get("Key features", "").splitlines() if x.strip().startswith("- ")]
    check("Key features ≤ 7 bullets", 0 < len(feats) <= 7, f"{len(feats)} bullets")
    check("No code blocks", "```" not in md and "<code" not in out_html, "")
    tags = set(re.findall(r"</?([a-z0-9]+)", out_html))
    check("HTML uses only h2/h3/p/ul/li/strong/a", tags <= {"h2", "h3", "p", "ul", "li", "strong", "a"},
          f"tags {sorted(tags)}")

    # 16.4 items
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    passed = {r["source"].split("[")[0] for r in probe["results"] if r["status"] == "PASS"}
    ds = secs.get("Data sources", "")
    claimed = {k for k, v in SOURCE_FAMILIES.items() if v.lower() in ds.split("\n- ")[0].lower()}
    check("≥ 2 data sources, matching probe PASS results", len(claimed) >= 2 and claimed <= passed,
          f"claimed {sorted(claimed)}; probe PASS {sorted(passed)}")
    check("NLP engine, sentiment, event classification, impact 1–10 present",
          all(k in low for k in ("nlp", "sentiment", "event classification", "impact score")) and
          ("1–10" in md or "1-10" in md or "1 to 10" in low), "")
    check("Structured machine-readable output present",
          all(k in low for k in ("api", "jsonl")) and ("server-sent events" in low or "sse" in low), "")
    check("Downstream module named and explained",
          "Module B: Strategic Portfolio Stress Testing was implemented." in md and "trigger" in low, "")
    check("Dashboard addressed", "dashboard" in low, "")
    deliv = secs.get("Deliverables", "")
    check("GitHub, live demo and 7-slide presentation addressed",
          all(k in deliv for k in ("GitHub repository:", "Live demonstration:", "Presentation (7 slides):")), "")
    allowed = allowed_numbers()
    res_nums = numbers_in(secs.get("Results", ""))
    untraced = [n for n in res_nums if n not in allowed]
    check("Every Results number traces to a script output", not untraced,
          f"{len(res_nums)} numbers checked; untraced: {untraced}")
    remaining = [p for p in PLACEHOLDERS if p in md]
    other_ph = [p for p in re.findall(r"\[[A-Z][A-Z0-9 ()/-]{3,}\]", md) if p not in PLACEHOLDERS]
    urls = re.findall(r"https?://\S+", md)
    check("No fabricated links; only the 3 allowed placeholders", not other_ph and (not urls or not remaining),
          f"placeholders remaining: {len(remaining)}; other placeholders: {other_ph}; urls: {len(urls)}")
    check("Synthetic, cached and simulated data clearly identified",
          all(k in md for k in ("SYNTHETIC", "CACHED_REAL")) and "simulated" in low, "")
    check("Business value explained; 'not investment advice' present",
          "This prototype is a decision-support tool, not investment advice." in md, "")
    lim = secs.get("Limitations", "")
    lim_bullets = [x for x in lim.splitlines() if x.strip().startswith("- ")]
    must = ["expert prior", "illustrative", "unofficial", "headline", "evaluation set"]
    check("Limitations honestly stated (≥ 5, required topics)",
          len(lim_bullets) >= 5 and all(k in lim.lower() for k in must), f"{len(lim_bullets)} bullets")
    days = sorted({f.name[8:16] for f in (ROOT / "data" / "cache" / "captures").glob("capture_*.jsonl")})
    fmt = [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in days]
    expected = (f"captured on {fmt[0]}" if len(fmt) == 1 else f"captured between {fmt[0]} and {fmt[-1]}") if fmt else ""
    check("Cached-data capture date matches data/cache/captures", bool(expected) and expected in md,
          f"expected phrase: '{expected}'")
    ev = json.loads(EVAL.read_text(encoding="utf-8"))
    check("Unreviewed labels flagged PRELIMINARY", (not ev["preliminary"]) or "PRELIMINARY" in secs.get("Results", ""),
          f"eval preliminary={ev['preliminary']}")

    width = max(len(c[0]) for c in checks)
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed · wrote {HTML_OUT.relative_to(ROOT)}")
    if remaining:
        print(f"NOT READY TO SUBMIT: {len(remaining)} link placeholder(s) remain: {', '.join(remaining)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
