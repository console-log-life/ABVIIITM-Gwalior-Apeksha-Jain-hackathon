"""Build docs/presentation/Risk_Signal_Engine.pptx (EXACTLY 7 slides, 16:9) with python-pptx.

Every number is read from a script output at build time, never typed in:
  data/eval/eval_results.json (src/scripts/evaluate.py) · data/eval/benchmark_results.json
  (src/scripts/benchmark_latency.py)
  data/eval/trigger_replay_*.json (src/scripts/replay_trigger_report.py) · StressEngine.run (portfolio/) · weights.yaml
Accuracy is labelled PRELIMINARY while any eval label is still draft_agent; stress figures are labelled as the
illustrative model on a synthetic portfolio.
Screenshots: run src/scripts/screenshot_dashboard.py, then src/scripts/crop_screenshots.py, before building.

Usage:  python src/scripts/build_presentation.py        (requires requirements-dev.txt: python-pptx)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

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
        "history": _history_meta(s),
    }


def _history_meta(settings) -> dict | None:
    """REAL history metadata written by src/risk_engine/history.py (None on a fresh clone without the cache)."""
    from risk_engine.history import history_path, read_meta

    return read_meta(history_path(settings))


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
         note or "Risk Signal Engine · decision support, not investment advice",
         size=18, color=MUTED, name="Footer")
    text(slide, W - MARGIN - Inches(0.8), H - Inches(0.45), Inches(0.8), Inches(0.3), f"{n} / 7", size=18,
         color=MUTED, align=PP_ALIGN.RIGHT, name="SlideNo")


def picture(slide, path, x, y, w=None, h=None, border=True):
    pic = slide.shapes.add_picture(str(path), x, y, width=w, height=h)
    if border:
        pic.line.color.rgb = LINE
        pic.line.width = Pt(1)
    return pic


def caption(slide, x, y, w, t, color=MUTED, size=18):
    text(slide, x, y, w, Inches(0.35), t, size=size, color=color, italic=True)


def notes(slide, t):
    slide.notes_slide.notes_text_frame.text = t


# ------------------------------------------------------------------ slides
def _flow(s, x0, y, items, color, filled) -> None:
    """Three rounded boxes with arrows (used for 'today' vs 'with the engine')."""
    bw2, gap2 = Inches(1.78), Inches(0.36)
    for i, it in enumerate(items):
        x = x0 + i * (bw2 + gap2)
        shp = card(s, x, y, bw2, Inches(1.0), fill=color if filled else TINT)
        tf = shp.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE
        for m in ("margin_left", "margin_right"):
            setattr(tf, m, Inches(0.1))
        p = tf.paragraphs[0]
        p.alignment = PP_ALIGN.CENTER
        r = p.add_run()
        r.text = it
        _font(r, 18, True, WHITE if filled else NAVY)
        if i < len(items) - 1:
            c = s.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x + bw2 + Inches(0.03), y + Inches(0.5),
                                       x + bw2 + gap2 - Inches(0.03), y + Inches(0.5))
            c.line.color.rgb = color
            c.line.width = Pt(2.5)
            c.line._get_or_add_ln().append(c.line._get_or_add_ln().makeelement(qn("a:tailEnd"),
                                                                                 {"type": "triangle"}))


def build(nums: dict) -> Presentation:
    """The official 7 slides: title · problem and approach · system design · implementation highlights · key results
    and metrics · domain impact and business value · limitations and future work."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    blank = prs.slide_layouts[6]
    prelim = "Preliminary (labels pending human review)" if nums["preliminary"] else "Human-reviewed labels"
    illus = "Illustrative model, synthetic portfolio"
    hist = nums.get("history") or {}

    # 1 ── title
    s = prs.slides.add_slide(blank)
    card(s, 0, 0, W, Inches(4.2), fill=NAVY)
    text(s, MARGIN, Inches(1.25), Inches(12), Inches(1.0), "Risk Signal Engine", size=54, bold=True, color=WHITE)
    text(s, MARGIN, Inches(2.35), Inches(12), Inches(0.7),
         "From breaking news and social posts to explainable risk signals and a portfolio stress test",
         size=24, color=WHITE)
    text(s, MARGIN, Inches(3.15), Inches(12), Inches(0.5),
         "S&P Global × CRISIL · Code to Connect 2026 · Module B: Strategic Portfolio Stress Testing",
         size=18, color=WHITE)
    facts = [(f"{hist.get('documents', '—'):,}" if hist else "—", "real captured headlines and posts"),
             ("1–10", "explainable impact score"), ("seconds", "from headline to portfolio view")]
    for i, (big, lab) in enumerate(facts):
        x = MARGIN + i * Inches(4.1)
        text(s, x, Inches(4.75), Inches(3.8), Inches(0.8), big, size=36, bold=True, color=TEAL)
        text(s, x, Inches(5.5), Inches(3.8), Inches(0.6), lab, size=18, color=INK)
    text(s, MARGIN, Inches(6.35), Inches(12), Inches(0.4), "Apeksha Jain · ABV-IIITM Gwalior · individual "
         "submission · decision support, not investment advice", size=18, color=MUTED)
    notes(s, "(30 s) Hello, I am Apeksha Jain from ABV-IIITM Gwalior. This is Risk Signal Engine, my individual "
             "submission for Module B, strategic portfolio stress testing. In one sentence: it reads news and social "
             "posts, turns each item into an explainable risk signal, and stress-tests the portfolio the moment "
             "something material happens. Every number I show comes from a script in the repository, or is "
             "labelled simulated.")

    # 2 ── problem and approach
    s = prs.slides.add_slide(blank)
    title(s, "Problem and approach", "Risk shows up in text before it shows up in data")
    bullets(s, MARGIN, BODY_TOP + Inches(0.1), Inches(5.6), Inches(4.8), [
        "Downgrades, probes, sanctions and rate moves break as headlines and posts",
        "Credit analysts and risk teams triage them by hand: slow, noisy, duplicated",
        "Nothing links a headline to the book's exposure until someone runs numbers",
        [("Approach: ", True), ("an NLP risk engine scores every item (sentiment, event, impact) and an "
                                "event-driven stress engine reprices the book", False)],
    ], size=19, space_after=10)
    text(s, Inches(6.7), BODY_TOP + Inches(0.3), Inches(6), Inches(0.4), "Today", size=20, bold=True, color=MUTED)
    _flow(s, Inches(6.7), BODY_TOP + Inches(0.85), ["Headline breaks", "Analyst reads it", "Manual stress run, later"],
          MUTED, False)
    text(s, Inches(6.7), BODY_TOP + Inches(2.55), Inches(6), Inches(0.4), "With the engine", size=20, bold=True,
         color=TEAL)
    _flow(s, Inches(6.7), BODY_TOP + Inches(3.1), ["Headline ingested", "Scored + explained", "Stress test triggered"],
          TEAL, True)
    caption(s, Inches(6.7), BODY_TOP + Inches(4.4), Inches(6),
            f"Measured: median {nums['lat_med']} ms per document (n = {nums['lat_n']})")
    footer(s, 2)
    notes(s, "(40 s) Credit risk shows up in text before it shows up in prices or ratings data: downgrades, "
             "regulatory probes, sanctions, rate surprises. Today an analyst reads the headline, decides whether it "
             "matters, and someone runs a stress test later, by hand. Nothing links the headline to the book's "
             "exposure in the moment. My approach: an NLP engine scores every item for sentiment, event type and a "
             "1-to-10 impact, and an event-driven stress engine reprices the portfolio when a rule fires. The only "
             f"speed claim I make is the measured one: a median of {nums['lat_med']} milliseconds per document on a "
             "CPU laptop.")

    # 3 ── system design with the architecture diagram
    s = prs.slides.add_slide(blank)
    title(s, "System design", "One NLP pipeline for live, replayed, scripted and API input")
    from PIL import Image

    arch = ROOT / "docs" / "architecture.png"
    aw, ah = Image.open(arch).size
    hh = Inches(5.3)
    ww = int(hh * aw / ah)
    if ww > W - 2 * MARGIN:
        ww = W - 2 * MARGIN
        hh = int(ww * ah / aw)
    picture(s, arch, int((W - ww) / 2), BODY_TOP - Inches(0.05), w=ww)
    footer(s, 3)
    notes(s, "(45 s) Left to right. Real sources, Google News, Reddit and Mastodon, are used only because they "
             "passed our probe script; the others are skipped cleanly, and no adapter can crash the app. Everything, "
             "live, replayed, scripted or sent to the API, goes through one pipeline: cleaning and deduplication, "
             "entity resolution, FinBERT sentiment, event rules with evidence, and the impact score. Signals are "
             "stored and published on an event bus; the stress engine is a subscriber, and the FastAPI service and "
             "the Streamlit dashboard sit on top. Every record carries a provenance badge, and after a one-time model "
             "download the whole system runs offline.")

    # 4 ── implementation highlights
    s = prs.slides.add_slide(blank)
    title(s, "Implementation highlights", "Every score is explained, every weight is published")
    bullets(s, MARGIN, BODY_TOP + Inches(0.05), Inches(5.4), Inches(5.2), [
        [("NLP: ", True), ("entities, FinBERT sentiment, 11 event classes with evidence", False)],
        [("Stress engine: ", True), ("news triggers with cooldown; bonds, loans, swaps, CDS, FX, equity", False)],
        [("Credit views: ", True), ("watchlist, propagation, one-click credit brief", False)],
        [("Engineering: ", True), ("one pipeline for every input, offline demo, time machine, audit trail", False)],
    ], size=18, space_after=16)
    w_ = nums["weights"]
    fx, fw = Inches(6.15), Inches(6.6)
    pic = picture(s, ASSETS / "explain_factors.png", fx, BODY_TOP - Inches(0.05), w=fw)
    caption(s, fx, BODY_TOP + Inches(0.02) + pic.height, fw,
            "Factor contributions for a SYNTHETIC demo signal")
    fy = Inches(5.2)
    card(s, MARGIN, fy, W - 2 * MARGIN, Inches(1.15), fill=WHITE, line=TEAL)
    text(s, MARGIN + Inches(0.3), fy + Inches(0.17), W - 2 * MARGIN - Inches(0.6), Inches(1.1), [
        [("Impact = 1 + 9 × Q × (", 24, True, NAVY), (f"{w_['E']:.2f}·E + {w_['M']:.2f}·M + {w_['X']:.2f}·X + "
                                                     f"{w_['R']:.2f}·R", 24, True, TEAL), (")", 24, True, NAVY)],
        [("E severity · M sentiment · X exposure · R credibility · Q confidence · ", 18, False, INK),
         ("uncalibrated expert priors", 18, False, MUTED)],
    ])
    footer(s, 4)
    notes(s, "(45 s) Three highlights. First, explainability: every score is decomposed. The impact formula is on "
             "the slide with the published weights: event severity, sentiment magnitude, exposure and source "
             "credibility, scaled by confidence. They are expert priors, not calibrated, and the dashboard says so. "
             "Second, the stress engine: news-only triggers, systemic or issuer-specific, with cooldown and "
             "corroboration, and simple pricers for bonds, loans, swaps, CDS, FX and equity. Third, credit views: an "
             "early-warning watchlist, propagation over curated links, a one-click credit brief, and a time machine "
             "over the real captured history.")

    # 5 ── key results and metrics
    s = prs.slides.add_slide(blank)
    title(s, "Key results and metrics", f"Accuracy: {prelim.lower()}")
    stats = [(f"{nums['sent_acc']}", "Sentiment", f"FinBERT · n = {nums['n']}"),
             (f"{nums['event_acc']}", "Events", f"rules · n = {nums['n']}"),
             (f"{nums['entity_acc']}", "Entities", f"n = {nums['n']}"),
             (f"{nums['lat_med']} ms", "Median latency", f"n = {nums['lat_n']} docs"),
             (f"{nums['runs_before']} → {nums['runs_after']}", "Stress runs", f"n = {nums['replay_docs']} real docs")]
    sw = Inches(2.3)
    for i, (big, lab, sub) in enumerate(stats):
        x = MARGIN + i * (sw + Inches(0.13))
        card(s, x, BODY_TOP, sw, Inches(1.5))
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.08), sw - Inches(0.3), Inches(0.6), big, size=28, bold=True,
             color=NAVY)
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.66), sw - Inches(0.3), Inches(0.4), lab, size=18, bold=True)
        text(s, x + Inches(0.18), BODY_TOP + Inches(1.03), sw - Inches(0.3), Inches(0.4), sub, size=18, color=MUTED)
    caption(s, MARGIN, BODY_TOP + Inches(1.55), Inches(12), "AI-drafted labels: a smoke test, not a benchmark.")
    y2 = BODY_TOP + Inches(2.05)
    text(s, MARGIN, y2, Inches(4.9), Inches(0.4), "Scenario demo (simulated)", size=19, bold=True, color=NAVY)
    labels = {"idiosyncratic_credit": "Tata Motors downgrade", "geopolitical_moderate": "Invasion (1 source)",
              "geopolitical_severe": "Corroborated (2 sources)"}
    for i, (key, lab) in enumerate(labels.items()):
        loss, rag, _ = nums["runs"][key]
        y = y2 + Inches(0.5) + i * Inches(0.5)
        dot = s.shapes.add_shape(MSO_SHAPE.OVAL, MARGIN, y + Inches(0.1), Inches(0.26), Inches(0.26))
        dot.fill.solid()
        dot.fill.fore_color.rgb = RISK[rag]
        dot.line.fill.background()
        dot.shadow.inherit = False
        text(s, MARGIN + Inches(0.42), y, Inches(4.4), Inches(0.46),
             [(f"{loss:.2f}% {rag}  ", 18, True, RISK[rag]), (lab, 18, False, INK)], anchor=MSO_ANCHOR.MIDDLE)
    if hist:
        text(s, MARGIN, y2 + Inches(2.1), Inches(4.9), Inches(0.8), [
            [("REAL history: ", 18, True, NAVY), (f"{hist['documents']:,} docs → {hist['stress_runs']} "
                                                  "simulated runs", 18, False, INK)]])
    pic = picture(s, ASSETS / "stress_waterfall.png", Inches(5.6), y2, w=Inches(7.15))
    caption(s, Inches(5.6), y2 + pic.height + Inches(0.03), Inches(7.15),
            "Before → after, corroborated geopolitical shock")
    text(s, MARGIN, H - Inches(0.85), W - 2 * MARGIN, Inches(0.35), STRESS_DISCLAIMER, size=18, color=RISK["RED"],
         bold=True, name="Disclaimer")
    footer(s, 5, note=f"Simulated losses · {illus.lower()} · not investment advice")
    l1, l2, l3 = (nums["runs"][k][0] for k in ("idiosyncratic_credit", "geopolitical_moderate", "geopolitical_severe"))
    notes(s, f"(60 s) Results, with n for every number. On {nums['n']} headlines and posts, FinBERT sentiment "
             f"accuracy is {nums['sent_acc']}, event classification {nums['event_acc']}, entity resolution "
             f"{nums['entity_acc']}. These labels were drafted by an AI assistant and are pending human review, so "
             f"treat them as a smoke test. Median latency is {nums['lat_med']} ms per document, p95 {nums['lat_p95']} "
             f"ms, over {nums['lat_n']} documents. Replaying {nums['replay_docs']} real captured documents, my "
             f"false-trigger fixes cut simulated stress runs from {nums['runs_before']} to {nums['runs_after']}. "
             f"In the scripted demo, a Tata Motors downgrade gives {l1:.2f}% GREEN thanks to a CDS hedge; an invasion "
             f"headline gives {l2:.2f}% AMBER; a second source corroborates it: {l3:.2f}% RED. These losses are "
             "simulated on a synthetic portfolio with an illustrative model, not investment advice.")

    # 6 ── domain impact and business value
    s = prs.slides.add_slide(blank)
    title(s, "Domain impact and business value", "Decision support for credit and portfolio risk")
    who = [("Credit analysts", "see which held names need attention, and why"),
           ("Risk managers", "get an audited portfolio view when news breaks"),
           ("Portfolio managers", "see linked exposure and test their own shocks")]
    cw = Inches(3.95)
    for i, (head, body) in enumerate(who):
        x = MARGIN + i * (cw + Inches(0.12))
        card(s, x, BODY_TOP, cw, Inches(1.4))
        text(s, x + Inches(0.2), BODY_TOP + Inches(0.1), cw - Inches(0.35), Inches(0.45), head, size=19, bold=True,
             color=NAVY)
        text(s, x + Inches(0.2), BODY_TOP + Inches(0.52), cw - Inches(0.35), Inches(0.8), body, size=18)
    y3 = BODY_TOP + Inches(1.6)
    hh = Inches(2.2)
    p1 = picture(s, ASSETS / "watchlist.png", MARGIN, y3, h=hh)
    p2 = picture(s, ASSETS / "credit_brief.png", MARGIN + p1.width + Inches(0.15), y3, h=hh)
    gx = p2.left + p2.width + Inches(0.15)
    p3 = picture(s, ASSETS / "propagation_graph.png", gx, y3, h=hh)
    if p3.left + p3.width > W - MARGIN:  # keep inside the margin: shrink to the remaining width, same aspect
        aspect = p3.height / p3.width
        p3.width = W - MARGIN - gx
        p3.height = int(p3.width * aspect)
    cy = y3 + hh + Inches(0.04)
    caption(s, MARGIN, cy, p1.width, "Watchlist on real news")
    caption(s, p2.left, cy, p2.width, "Credit brief (PDF)")
    caption(s, p3.left, cy, p3.width, "Propagation graph")
    card(s, MARGIN, Inches(5.95), W - 2 * MARGIN, Inches(0.85), fill=NAVY)
    text(s, MARGIN + Inches(0.4), Inches(5.95), W - 2 * MARGIN - Inches(0.8), Inches(0.85),
         "No ROI claims: earlier attention, triage with the reason shown, audit trail to the headline",
         size=22, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    footer(s, 6)
    notes(s, "(40 s) Who uses it. Credit analysts see which held names need attention and exactly which rule fired. "
             "Risk managers get an audited, simulated portfolio view when news breaks, instead of waiting for the "
             "next scheduled run. Portfolio managers see linked exposure and test their own shocks with the what-if "
             "sliders. I make no ROI or time-saved claim. The value is earlier attention, triage by materiality with "
             "the reason shown, and an audit trail from every stress run back to the headline that triggered it. "
             "Linked exposure is an attention measure, not a contagion model.")

    # 7 ── limitations and future work
    s = prs.slides.add_slide(blank)
    title(s, "Limitations and future work")
    cols = [("Limitations", ["Uncalibrated impact weights", "Rules still misfire at times", "Headline-only news",
                             "Small AI-labelled eval set", "Illustrative stress model"]),
            ("Future work", ["Calibrate on market moves", "Licensed full-text news", "Fine-tuned models (ready)",
                             "Streaming (Kafka)", "Backtesting"]),
            ("What already works", ["Provenance on every record", "One pipeline for all input",
                                    "Real-data time machine", "Trigger audit trail", "Offline laptop demo"])]
    cw = Inches(3.9)
    for i, (head, items) in enumerate(cols):
        x = MARGIN + i * (cw + Inches(0.17))
        card(s, x, BODY_TOP - Inches(0.25), cw, Inches(3.75))
        text(s, x + Inches(0.3), BODY_TOP - Inches(0.05), cw - Inches(0.5), Inches(0.5), head, size=22, bold=True,
             color=NAVY if i == 0 else TEAL)
        bullets(s, x + Inches(0.3), BODY_TOP + Inches(0.6), cw - Inches(0.55), Inches(2.9), items, size=18,
                space_after=14)
    card(s, MARGIN, Inches(5.35), W - 2 * MARGIN, Inches(1.2), fill=NAVY)
    text(s, MARGIN + Inches(0.4), Inches(5.35), W - 2 * MARGIN - Inches(0.8), Inches(1.2),
         "An honest, explainable bridge from text to portfolio risk, offline on a laptop",
         size=24, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    footer(s, 7)
    notes(s, "(40 s) Honest limitations: the impact weights are uncalibrated priors, keyword rules still misfire on "
             "some real headlines, news is headline-only, the evaluation set is small and AI-labelled, and the stress "
             "model is illustrative on a synthetic portfolio. Next: calibrate impact on market moves, licensed "
             "full-text news, fine-tuned models from the ready training notebook, streaming and backtesting. What "
             "already works: provenance on every record, one pipeline for every input, and an offline demo on a "
             "laptop. Thank you, I am happy to take questions.")
    return prs


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
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
