"""Build docs/presentation/Risk_Signal_Engine.pptx (EXACTLY 7 slides, 16:9) with python-pptx.

Every number is read from a script output at build time, never typed in:
  data/eval/eval_results.json (scripts/evaluate.py) · data/eval/benchmark_results.json (scripts/benchmark_latency.py)
  data/eval/trigger_replay_*.json (scripts/replay_trigger_report.py) · StressEngine.run (portfolio/) · weights.yaml
Accuracy is labelled PRELIMINARY while any eval label is still draft_agent; stress figures are labelled as the
illustrative model on a synthetic portfolio.
Screenshots: run scripts/screenshot_dashboard.py, then scripts/crop_screenshots.py, before building.

Usage:  python scripts/build_presentation.py        (requires requirements-dev.txt: python-pptx)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import STRESS_DISCLAIMER, get_settings  # noqa: E402
from portfolio.stress_engine import StressEngine  # noqa: E402
from risk_engine.impact_scoring.scorer import get_scorer  # noqa: E402

OUT = ROOT / "docs" / "presentation" / "Risk_Signal_Engine.pptx"
ASSETS = ROOT / "docs" / "presentation" / "assets"
EVAL = ROOT / "data" / "eval"

NAVY = RGBColor(0x1F, 0x2A, 0x44)
TEAL = RGBColor(0x0E, 0x8A, 0x84)
INK = RGBColor(0x1A, 0x1A, 0x1A)
MUTED = RGBColor(0x55, 0x5B, 0x66)
TINT = RGBColor(0xEE, 0xF4, 0xF6)  # light card fill
LINE = RGBColor(0xC9, 0xD3, 0xDB)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
RISK = {"GREEN": RGBColor(0x0C, 0xA3, 0x0C), "AMBER": RGBColor(0xC9, 0x8A, 0x00), "RED": RGBColor(0xD0, 0x3B, 0x3B)}
FONT = "Calibri"
W, H = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.6)
TITLE_TOP = Inches(0.45)
BODY_TOP = Inches(1.55)


# ------------------------------------------------------------------ numbers (from script outputs only)
def load_numbers() -> dict:
    ev = json.loads((EVAL / "eval_results.json").read_text(encoding="utf-8"))
    bench = json.loads((EVAL / "benchmark_results.json").read_text(encoding="utf-8"))
    rep = {}
    for label in ("before", "n2_task2"):
        p = EVAL / f"trigger_replay_{label}.json"
        rep[label] = json.loads(p.read_text(encoding="utf-8"))
    s = get_settings()
    eng = StressEngine(s)
    runs = {name: eng.run(name, "IN-TATAMOTORS" if name == "idiosyncratic_credit" else None)[0]
            for name in ("idiosyncratic_credit", "geopolitical_moderate", "geopolitical_severe")}
    social_before = sum(v for k, v in rep["before"]["runs_by_source"].items() if k not in ("google_news", "gdelt",
                                                                                           "finnhub"))
    return {
        "n": ev["n"], "preliminary": ev["preliminary"],
        "sent_acc": ev["sentiment_finbert"]["accuracy"], "event_acc": ev["event_rules"]["accuracy"],
        "entity_acc": ev["entity"]["accuracy"],
        "lat_med": bench["per_document_ms"]["median"], "lat_p95": bench["per_document_ms"]["p95"],
        "lat_n": bench["n_documents"],
        "replay_docs": rep["before"]["documents"], "runs_before": rep["before"]["stress_runs"],
        "runs_after": rep["n2_task2"]["stress_runs"], "social_before": social_before,
        "social_after": sum(v for k, v in rep["n2_task2"]["runs_by_source"].items()
                            if k not in ("google_news", "gdelt", "finnhub")),
        "positions": len(eng.portfolio.df), "funded_mv_m": eng.portfolio.funded_mv / 1e6,
        "runs": {k: (v["loss_pct"], v["rag"], v["scenario_label"]) for k, v in runs.items()},
        "weights": get_scorer().cfg["weights"],
    }


# ------------------------------------------------------------------ drawing helpers
def _font(run, size, bold=False, color=INK, italic=False):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color


def text(slide, x, y, w, h, content, size=20, bold=False, color=INK, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, italic=False, name=None):
    """content: str or list of (text, size, bold, color) runs on one paragraph, or list of such lists (paragraphs)."""
    box = slide.shapes.add_textbox(x, y, w, h)
    if name:
        box.name = name
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Emu(0))
    paras = [[(content, size, bold, color)]] if isinstance(content, str) else (
        [content] if content and isinstance(content[0], tuple) else content)
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        for t, sz, b, c in para:
            r = p.add_run()
            r.text = t
            _font(r, sz, b, c, italic)
    return box


def bullets(slide, x, y, w, h, items, size=20, color=INK, space_after=10):
    box = slide.shapes.add_textbox(x, y, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
        setattr(tf, m, Emu(0))
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        ppr = p._p.get_or_add_pPr()
        ppr.set("marL", str(Inches(0.3)))
        ppr.set("indent", str(-Inches(0.3)))
        bu_clr = ppr.makeelement(qn("a:buClr"), {})
        srgb = bu_clr.makeelement(qn("a:srgbClr"), {"val": "0E8A84"})
        bu_clr.append(srgb)
        ppr.append(bu_clr)
        ppr.append(ppr.makeelement(qn("a:buFont"), {"typeface": "Arial"}))
        ppr.append(ppr.makeelement(qn("a:buChar"), {"char": "•"}))
        p.space_after = Pt(space_after)
        runs = item if isinstance(item, list) else [(item, False)]
        for t, b in runs:
            r = p.add_run()
            r.text = t
            _font(r, size, b, color)
    return box


def card(slide, x, y, w, h, fill=TINT, line=None, name=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shp.adjustments[0] = 0.06
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line is None:
        shp.line.fill.background()
    else:
        shp.line.color.rgb = line
        shp.line.width = Pt(1.25)
    shp.shadow.inherit = False
    if name:
        shp.name = name
    return shp


def title(slide, t, sub=None):
    text(slide, MARGIN, TITLE_TOP, W - 2 * MARGIN, Inches(0.75), t, size=36, bold=True, color=NAVY, name="Title")
    if sub:
        text(slide, MARGIN, TITLE_TOP + Inches(0.7), W - 2 * MARGIN, Inches(0.4), sub, size=18, color=TEAL,
             name="Subtitle")


def footer(slide, n, note=None):
    text(slide, MARGIN, H - Inches(0.45), Inches(9.5), Inches(0.3),
         note or "Risk Signal Engine · Code to Connect 2026 · decision-support prototype, not investment advice",
         size=11, color=MUTED, name="Footer")
    text(slide, W - MARGIN - Inches(0.8), H - Inches(0.45), Inches(0.8), Inches(0.3), f"{n} / 7", size=11,
         color=MUTED, align=PP_ALIGN.RIGHT, name="SlideNo")


def picture(slide, path, x, y, w=None, h=None, border=True):
    pic = slide.shapes.add_picture(str(path), x, y, width=w, height=h)
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(1)
    return pic


def caption(slide, x, y, w, t, color=MUTED, size=12):
    text(slide, x, y, w, Inches(0.3), t, size=size, color=color, italic=True)


def notes(slide, t):
    slide.notes_slide.notes_text_frame.text = t


# ------------------------------------------------------------------ slides
def build(nums: dict) -> Presentation:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    prelim = "Preliminary (labels pending human review)" if nums["preliminary"] else "Human-reviewed labels"
    illus = "Illustrative model, synthetic portfolio"

    # 1 ── title + problem + one-line solution
    s = prs.slides.add_slide(blank)
    text(s, MARGIN, Inches(1.0), Inches(12), Inches(1.0), "Risk Signal Engine", size=48, bold=True, color=NAVY)
    text(s, MARGIN, Inches(1.95), Inches(12), Inches(0.6),
         "From breaking news and social posts to a portfolio stress test, automatically", size=24, color=TEAL)
    for i, (head, body) in enumerate([
        ("The problem", "Downgrades, sanctions, probes and rate moves hit unstructured text first. "
                        "Risk teams read them by hand, and the portfolio impact is worked out later."),
        ("Our solution", "An NLP engine scores every item for sentiment, event type and a transparent 1–10 "
                         "impact, then triggers a stress test of a loans, bonds and derivatives book."),
    ]):
        x = MARGIN + i * Inches(6.15)
        card(s, x, Inches(3.05), Inches(5.9), Inches(2.6))
        text(s, x + Inches(0.35), Inches(3.3), Inches(5.2), Inches(0.5), head, size=24, bold=True, color=NAVY)
        text(s, x + Inches(0.35), Inches(3.9), Inches(5.2), Inches(1.7), body, size=20)
    text(s, MARGIN, Inches(6.05), Inches(12), Inches(0.4),
         "S&P Global × CRISIL · Code to Connect Hackathon 2026 · Module B: Strategic Portfolio Stress Testing",
         size=16, color=MUTED)
    footer(s, 1)
    notes(s, "Every number you will see is either measured by a script in the repository or clearly labelled as "
             "simulated or synthetic. The problem: risk-relevant events surface in text first, and nothing connects "
             "them to the portfolio until someone reads and calculates. Our answer: an NLP risk engine plus an "
             "event-driven stress test.")

    # 2 ── business context
    s = prs.slides.add_slide(blank)
    title(s, "Why it matters", "Risk shows up in text before it shows up in data")
    bullets(s, MARGIN, BODY_TOP + Inches(0.1), Inches(5.6), Inches(4.6), [
        "Credit analysts and risk teams monitor hundreds of issuers",
        "Downgrades, probes and sanctions break as headlines and posts",
        "Manual triage is slow, noisy and duplicated",
        "Nothing links a headline to the book's exposure",
        [("Need: ", True), ("early warning, materiality ranking, instant portfolio view", False)],
    ], size=20)
    steps = [("Today", ["Headline breaks", "Analyst reads it", "Manual stress run, later"], MUTED),
             ("With the engine", ["Headline ingested", "Scored + explained", "Stress test triggered"], TEAL)]
    for row, (label, items, color) in enumerate(steps):
        y = BODY_TOP + Inches(0.3) + row * Inches(2.25)
        text(s, Inches(6.7), y, Inches(6), Inches(0.4), label, size=20, bold=True, color=color)
        bw2, gap2 = Inches(1.78), Inches(0.36)
        for i, it in enumerate(items):
            x = Inches(6.7) + i * (bw2 + gap2)
            shp = card(s, x, y + Inches(0.55), bw2, Inches(1.0), fill=color if row else TINT)
            tf = shp.text_frame
            tf.word_wrap = True
            tf.vertical_anchor = MSO_ANCHOR.MIDDLE
            for m in ("margin_left", "margin_right"):
                setattr(tf, m, Inches(0.1))
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            r = p.add_run()
            r.text = it
            _font(r, 18, True, WHITE if row else NAVY)
            if i < len(items) - 1:
                c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x + bw2 + Inches(0.03), y + Inches(1.05),
                                           x + bw2 + gap2 - Inches(0.03), y + Inches(1.05))
                c.line.color.rgb = color
                c.line.width = Pt(2.5)
                c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(qn("a:tailEnd"),
                                                                                     {"type": "triangle"}))
    caption(s, Inches(6.7), BODY_TOP + Inches(4.75), Inches(6),
            f"Measured pipeline latency: median {nums['lat_med']} ms per document (n = {nums['lat_n']}, CPU laptop)")
    footer(s, 2)
    notes(s, "Frame this as decision support, not trading signals. Users: risk managers, credit analysts, portfolio "
             "managers. We make no ROI or time-saved claim; the only speed number is the measured per-document "
             "latency of the pipeline.")

    # 3 ── architecture (native shapes)
    s = prs.slides.add_slide(blank)
    title(s, "Architecture", "One NLP pipeline for live, replay, scripted demo and API input")
    boxes = [("Sources", "Google News, Reddit, Mastodon"),
             ("Ingestion", "Rate limits, retries, dedup"),
             ("NLP pipeline", "Entities, FinBERT, events, impact"),
             ("Signals", "SQLite, bus, REST, SSE, JSONL"),
             ("Stress engine", "Module B triggers and pricers"),
             ("Dashboard", "12 sections and explanations")]
    bw, gap, y = Inches(1.82), Inches(0.27), Inches(2.25)
    for i, (head, body) in enumerate(boxes):
        x = MARGIN + i * (bw + gap)
        key = head in ("NLP pipeline", "Stress engine")
        card(s, x, y, bw, Inches(2.55), fill=NAVY if key else TINT, name=f"Arch{i}")
        text(s, x + Inches(0.15), y + Inches(0.2), bw - Inches(0.3), Inches(0.5), head, size=19, bold=True,
             color=WHITE if key else NAVY)
        text(s, x + Inches(0.15), y + Inches(0.8), bw - Inches(0.3), Inches(1.7), body, size=18,
             color=WHITE if key else INK)
        if i < len(boxes) - 1:
            c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x + bw + Inches(0.02), y + Inches(1.27),
                                       x + bw + gap - Inches(0.02), y + Inches(1.27))
            c.line.color.rgb = TEAL
            c.line.width = Pt(2.5)
            c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(qn("a:tailEnd"), {"type": "triangle"}))
    text(s, MARGIN, Inches(5.15), W - 2 * MARGIN, Inches(0.45), "Every record carries its provenance", size=20,
         bold=True, color=NAVY)
    x = MARGIN
    for tag, desc, cw_ in [("LIVE", "fetched now", 3.1), ("CACHED_REAL", "real, captured earlier", 4.25),
                           ("SYNTHETIC", "demo, user text, portfolio", 4.38)]:
        card(s, x, Inches(5.65), Inches(cw_), Inches(0.75), fill=WHITE, line=LINE)
        text(s, x + Inches(0.2), Inches(5.65), Inches(cw_ - 0.3), Inches(0.75),
             [(tag + "  ", 18, True, TEAL), (desc, 18, False, INK)], anchor=MSO_ANCHOR.MIDDLE)
        x += Inches(cw_ + 0.2)
    footer(s, 3)
    notes(s, "Sources are only claimed after our probe script passed on this machine. Adapters never crash the app: "
             "timeouts, bounded retries and backoff, with health shown in the dashboard. The stress engine is just a "
             "subscriber on the event bus. The whole demo runs offline after a one-time model download.")

    # 4 ── NLP risk engine incl. impact formula
    s = prs.slides.add_slide(blank)
    title(s, "NLP risk engine", "Every score is explained, every weight is published")
    bullets(s, MARGIN, BODY_TOP + Inches(0.1), Inches(5.2), Inches(5.0), [
        [("Entities: ", True), ("cashtags → aliases → spaCy → guarded fuzzy → MARKET", False)],
        [("Sentiment: ", True), ("FinBERT, s = P(pos) − P(neg), lexicon fallback", False)],
        [("Events: ", True), ("11-class rules with evidence phrases; zero-shot tested, kept off", False)],
        [("Explainability: ", True), ("probabilities, evidence, factors, reason, business implication", False)],
        [("Output: ", True), ("RiskSignal JSON via REST, SSE stream, JSONL export", False)],
    ], size=20, space_after=14)
    w_ = nums["weights"]
    fx, fw = Inches(6.15), Inches(6.6)
    fy = BODY_TOP + Inches(2.85)
    card(s, fx, fy, fw, Inches(1.85), fill=WHITE, line=TEAL)
    text(s, fx + Inches(0.25), fy + Inches(0.18), fw - Inches(0.5), Inches(1.95), [
        [("Impact = 1 + 9 × Q × (", 19, True, NAVY), (f"{w_['E']:.2f}·E + {w_['M']:.2f}·M + {w_['X']:.2f}·X + "
                                                     f"{w_['R']:.2f}·R", 19, True, TEAL), (")", 19, True, NAVY)],
        [("E event severity · M sentiment magnitude · X exposure · R credibility + corroboration · Q confidence",
          18, False, INK)],
        [("Expert-set priors, not calibrated", 18, False, MUTED)],
    ])
    pic = picture(s, ASSETS / "explain_factors.png", Inches(6.15), BODY_TOP - Inches(0.05), w=Inches(6.6))
    caption(s, Inches(6.15), BODY_TOP + Inches(0.02) + pic.height, Inches(6.6),
            "Dashboard explainability: factor contributions for a SYNTHETIC demo signal")
    footer(s, 4)
    notes(s, "Walk through the formula with the example on the right: event severity and strong negative sentiment "
             "dominate, the signal is market-wide, and two independent sources corroborate it. The weights are "
             "expert priors, published at /methodology; calibration against market reactions is future work.")

    # 5 ── stress testing with waterfall
    s = prs.slides.add_slide(blank)
    title(s, "Stress testing (Module B)", "High-impact news triggers a stress test of the book")
    bullets(s, MARGIN, BODY_TOP + Inches(0.1), Inches(4.7), Inches(3.4), [
        f"{nums['positions']} positions, ${nums['funded_mv_m']:.0f}m funded: loans, bonds, IRS, CDS hedges, FX, equity",
        "Systemic: market-wide or corroborated, news-sourced, impact ≥ 7",
        "Issuer: credit/regulatory/legal, held issuer, negative news",
        "Cooldown and an audit trail for every run",
    ], size=18)
    labels = {"idiosyncratic_credit": "Tata Motors downgrade", "geopolitical_moderate": "Invasion (1 source)",
              "geopolitical_severe": "Corroborated (2 sources)"}
    for i, (key, lab) in enumerate(labels.items()):
        loss, rag, _ = nums["runs"][key]
        y = Inches(4.95) + i * Inches(0.6)
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, MARGIN, y + Inches(0.1), Inches(0.28), Inches(0.28))
        dot.fill.solid()
        dot.fill.fore_color.rgb = RISK[rag]
        dot.line.fill.background()
        dot.shadow.inherit = False
        text(s, MARGIN + Inches(0.45), y, Inches(4.3), Inches(0.5),
             [(f"{loss:.2f}% {rag}  ", 19, True, RISK[rag]), (lab, 18, False, INK)], anchor=MSO_ANCHOR.MIDDLE)
    pic = picture(s, ASSETS / "stress_waterfall.png", Inches(5.65), BODY_TOP + Inches(0.1), w=Inches(7.1))
    caption(s, Inches(5.65), BODY_TOP + Inches(0.2) + pic.height, Inches(7.1),
            f"Before → after, corroborated geopolitical shock · {illus}")
    text(s, Inches(5.65), BODY_TOP + Inches(0.6) + pic.height, Inches(7.1), Inches(0.7), STRESS_DISCLAIMER,
         size=14, color=RISK["RED"], bold=True)
    footer(s, 5, note=f"Demo losses: simulated, {illus.lower()} · not investment advice")
    notes(s, "Read the disclaimer aloud. In the demo the Tata Motors downgrade triggers an issuer-only stress; our "
             "CDS hedge offsets much of it. The invasion headline triggers a moderate systemic stress; a second "
             "independent source escalates it to severe, above our 2% risk appetite.")

    # 6 ── results + dashboard + business impact
    s = prs.slides.add_slide(blank)
    title(s, "Results and dashboard", f"Accuracy: {prelim.lower()}")
    stats = [(f"{nums['sent_acc']}", "Sentiment", f"accuracy · FinBERT · n = {nums['n']}"),
             (f"{nums['event_acc']}", "Events", f"accuracy · rules · n = {nums['n']}"),
             (f"{nums['entity_acc']}", "Entities", f"accuracy · n = {nums['n']}"),
             (f"{nums['lat_med']} ms", "Median latency", f"p95 {nums['lat_p95']} ms · n = {nums['lat_n']}"),
             (f"{nums['runs_before']} → {nums['runs_after']}", "Stress runs",
              f"replay after fixes · n = {nums['replay_docs']}")]
    sw = Inches(2.3)
    for i, (big, lab, sub) in enumerate(stats):
        x = MARGIN + i * (sw + Inches(0.13))
        card(s, x, BODY_TOP, sw, Inches(1.55))
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.1), sw - Inches(0.3), Inches(0.6), big, size=30, bold=True,
             color=NAVY)
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.72), sw - Inches(0.3), Inches(0.4), lab, size=18, bold=True)
        text(s, x + Inches(0.18), BODY_TOP + Inches(1.08), sw - Inches(0.3), Inches(0.35), sub, size=12, color=MUTED)
    caption(s, MARGIN, BODY_TOP + Inches(1.62), Inches(12), f"{prelim}: labels drafted by an AI assistant, which also "
            "wrote the event rules. Treat as a smoke test, not a benchmark.", size=12)
    y2 = BODY_TOP + Inches(2.1)
    from PIL import Image

    avail, gap_i = W - 2 * MARGIN - Inches(0.25), Inches(0.25)
    ratios = [Image.open(ASSETS / f).size for f in ("home_kpis.png", "signals_charts.png")]
    hh = int(avail / sum(w_ / h_ for w_, h_ in ratios))  # common height so both fit the width exactly
    p1 = picture(s, ASSETS / "home_kpis.png", MARGIN, y2, h=hh)
    picture(s, ASSETS / "signals_charts.png", MARGIN + p1.width + gap_i, y2, h=hh)
    text(s, MARGIN, y2 + hh + Inches(0.15), Inches(12.1), Inches(0.5),
         [("Business impact: ", 18, True, NAVY), ("earlier warning, triage by materiality, an audited portfolio view "
                                                 "in seconds. Decision support, not investment advice.", 18, False,
                                                 INK)])
    footer(s, 6)
    notes(s, "State the caveat plainly: the evaluation labels were drafted by an AI assistant and are pending human "
             "review, and the same assistant wrote the rules, so those numbers are a smoke test. Replaying 911 real "
             "captured documents, our false-trigger fixes cut simulated stress runs from 84 to 50 and removed every "
             "run triggered by social posts alone.")

    # 7 ── innovation + limitations + future + takeaway
    s = prs.slides.add_slide(blank)
    title(s, "What is new, what is not, what is next")
    cols = [("Innovation", ["Provenance on every record", "One pipeline for live, replay and demo",
                            "Corroboration escalates severity", "Trigger audit trail with the cause"]),
            ("Limitations", ["Weights are uncalibrated priors", "Keyword rules still misfire",
                             "Headline-only news text", "Small AI-labelled eval set", "Illustrative stress model"]),
            ("Next", ["Kafka streaming", "Calibrate impact on market moves", "Licensed full-text news",
                      "Backtesting, full revaluation"])]
    cw = Inches(3.9)
    for i, (head, items) in enumerate(cols):
        x = MARGIN + i * (cw + Inches(0.17))
        card(s, x, BODY_TOP - Inches(0.25), cw, Inches(3.85))
        text(s, x + Inches(0.3), BODY_TOP - Inches(0.05), cw - Inches(0.5), Inches(0.5), head, size=22, bold=True,
             color=TEAL if i != 1 else NAVY)
        bullets(s, x + Inches(0.3), BODY_TOP + Inches(0.55), cw - Inches(0.55), Inches(2.9), items, size=18,
                space_after=6)
    card(s, MARGIN, Inches(5.45), W - 2 * MARGIN, Inches(1.2), fill=NAVY)
    text(s, MARGIN + Inches(0.4), Inches(5.45), W - 2 * MARGIN - Inches(0.8), Inches(1.2),
         "An honest, explainable bridge from text to portfolio risk that runs offline on a laptop.",
         size=24, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    footer(s, 7)
    notes(s, "Close on the takeaway and invite the judges to type their own headline into the dashboard. If asked "
             "about weaknesses, the limitations column is the honest list; docs/judge_qa.md has the answers.")
    return prs


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    nums = load_numbers()
    prs = build(nums)
    assert len(prs.slides) == 7, "the deck must have exactly 7 slides"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(OUT)
    print(f"wrote {OUT.relative_to(ROOT)} (7 slides); numbers: " + json.dumps(
        {k: v for k, v in nums.items() if k not in ("weights", "runs")}) + f"; runs {nums['runs']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
