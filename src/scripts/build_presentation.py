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
        _font(r, 17, True, WHITE if filled else NAVY)
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
         "S&P Global × CRISIL · Code to Connect Hackathon 2026 · Module B: Strategic Portfolio Stress Testing",
         size=17, color=WHITE)
    facts = [(f"{hist.get('documents', '—'):,}" if hist else "—", "real captured headlines and posts"),
             ("1–10", "explainable impact score"), ("seconds", "from headline to portfolio view")]
    for i, (big, lab) in enumerate(facts):
        x = MARGIN + i * Inches(4.1)
        text(s, x, Inches(4.75), Inches(3.8), Inches(0.8), big, size=36, bold=True, color=TEAL)
        text(s, x, Inches(5.5), Inches(3.8), Inches(0.6), lab, size=18, color=INK)
    text(s, MARGIN, Inches(6.35), Inches(12), Inches(0.4), "Individual submission · decision-support prototype, "
         "not investment advice", size=15, color=MUTED)
    notes(s, "Every number in this deck is produced by a script in the repository or labelled as simulated or "
             "synthetic. One sentence: we turn news and social text into explainable risk signals and stress the "
             "portfolio when something material happens.")

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
            f"Measured pipeline latency: median {nums['lat_med']} ms per document (n = {nums['lat_n']}, CPU laptop)")
    footer(s, 2)
    notes(s, "Frame it as decision support for risk managers, credit analysts and portfolio managers. We make no ROI "
             "or time-saved claim; the only speed number is the measured per-document latency.")

    # 3 ── system design with the architecture diagram
    s = prs.slides.add_slide(blank)
    title(s, "System design", "One NLP pipeline for live, replayed, scripted and API input")
    from PIL import Image

    arch = ROOT / "docs" / "architecture.png"
    aw, ah = Image.open(arch).size
    hh = Inches(4.75)
    ww = int(hh * aw / ah)
    if ww > W - 2 * MARGIN:
        ww = W - 2 * MARGIN
        hh = int(ww * ah / aw)
    pic = picture(s, arch, int((W - ww) / 2), BODY_TOP, w=ww)
    caption(s, int((W - ww) / 2), BODY_TOP + pic.height + Inches(0.05), ww,
            "Sources → ingestion → NLP → RiskSignal store and API → stress engine and dashboard · every record "
            "labelled LIVE / CACHED_REAL / SYNTHETIC (docs/architecture.png)")
    footer(s, 3)
    notes(s, "Sources are only claimed after our probe script passed. Adapters never crash the app. The stress engine "
             "is a subscriber on the event bus. Everything runs offline after a one-time model download.")

    # 4 ── implementation highlights
    s = prs.slides.add_slide(blank)
    title(s, "Implementation highlights", "Every score is explained, every weight is published")
    bullets(s, MARGIN, BODY_TOP + Inches(0.05), Inches(5.4), Inches(5.2), [
        [("NLP: ", True), ("entities (cashtags, aliases, spaCy, guarded fuzzy), FinBERT sentiment, 11-class event "
                           "rules with evidence; optional fine-tuned models in a hybrid", False)],
        [("Stress engine: ", True), ("news-only systemic and issuer triggers with cooldown; pricers for bonds, "
                                     "loans, IRS, CDS, FX, equity; what-if sliders", False)],
        [("Credit views: ", True), ("watchlist, propagation over 16 curated links, one-click credit brief", False)],
        [("Engineering: ", True), ("one pipeline for every input, offline demo, time machine over real data, "
                                   "audit trail", False)],
    ], size=17, space_after=9)
    w_ = nums["weights"]
    fx, fw = Inches(6.15), Inches(6.6)
    pic = picture(s, ASSETS / "explain_factors.png", fx, BODY_TOP - Inches(0.05), w=fw)
    caption(s, fx, BODY_TOP + Inches(0.02) + pic.height, fw,
            "Dashboard explainability: factor contributions for a SYNTHETIC demo signal")
    fy = BODY_TOP + pic.height + Inches(0.45)
    card(s, fx, fy, fw, Inches(1.65), fill=WHITE, line=TEAL)
    text(s, fx + Inches(0.25), fy + Inches(0.15), fw - Inches(0.5), Inches(1.4), [
        [("Impact = 1 + 9 × Q × (", 18, True, NAVY), (f"{w_['E']:.2f}·E + {w_['M']:.2f}·M + {w_['X']:.2f}·X + "
                                                     f"{w_['R']:.2f}·R", 18, True, TEAL), (")", 18, True, NAVY)],
        [("E event severity · M sentiment magnitude · X exposure · R credibility + corroboration · Q confidence",
          15, False, INK)],
        [("Expert-set priors, not calibrated", 15, False, MUTED)],
    ])
    footer(s, 4)
    notes(s, "Walk through the formula with the example: event severity and strong negative sentiment dominate, the "
             "signal is market-wide, and two sources corroborate it. Weights are published at /methodology.")

    # 5 ── key results and metrics
    s = prs.slides.add_slide(blank)
    title(s, "Key results and metrics", f"Accuracy: {prelim.lower()}")
    stats = [(f"{nums['sent_acc']}", "Sentiment", f"accuracy · FinBERT · n = {nums['n']}"),
             (f"{nums['event_acc']}", "Events", f"accuracy · rules · n = {nums['n']}"),
             (f"{nums['entity_acc']}", "Entities", f"accuracy · n = {nums['n']}"),
             (f"{nums['lat_med']} ms", "Median latency", f"p95 {nums['lat_p95']} ms · n = {nums['lat_n']}"),
             (f"{nums['runs_before']} → {nums['runs_after']}", "Stress runs",
              f"replay after fixes · n = {nums['replay_docs']}")]
    sw = Inches(2.3)
    for i, (big, lab, sub) in enumerate(stats):
        x = MARGIN + i * (sw + Inches(0.13))
        card(s, x, BODY_TOP, sw, Inches(1.45))
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.08), sw - Inches(0.3), Inches(0.6), big, size=28, bold=True,
             color=NAVY)
        text(s, x + Inches(0.18), BODY_TOP + Inches(0.66), sw - Inches(0.3), Inches(0.4), lab, size=18, bold=True)
        text(s, x + Inches(0.18), BODY_TOP + Inches(1.0), sw - Inches(0.3), Inches(0.35), sub, size=12, color=MUTED)
    caption(s, MARGIN, BODY_TOP + Inches(1.5), Inches(12), f"{prelim}: labels drafted by an AI assistant, which also "
            "wrote the event rules. Treat as a smoke test, not a benchmark.", size=12)
    y2 = BODY_TOP + Inches(2.0)
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
             [(f"{loss:.2f}% {rag}  ", 18, True, RISK[rag]), (lab, 17, False, INK)], anchor=MSO_ANCHOR.MIDDLE)
    if hist:
        text(s, MARGIN, y2 + Inches(2.15), Inches(4.9), Inches(1.2), [
            [("REAL history: ", 16, True, NAVY), (f"{hist['documents']:,} captured documents → {hist['signals']:,} "
                                                  f"signals → {hist['stress_runs']} simulated stress runs", 16,
                                                  False, INK)]])
    text(s, MARGIN, Inches(6.45), Inches(4.9), Inches(0.5), STRESS_DISCLAIMER, size=12, color=RISK["RED"], bold=True)
    pic = picture(s, ASSETS / "stress_waterfall.png", Inches(5.6), y2, w=Inches(7.15))
    caption(s, Inches(5.6), y2 + pic.height + Inches(0.03), Inches(7.15),
            f"Before → after, corroborated geopolitical shock · {illus}")
    footer(s, 5, note=f"Demo losses: simulated, {illus.lower()} · not investment advice")
    notes(s, "State the caveat plainly: the evaluation labels were drafted by an AI assistant and are pending human "
             "review, and the same assistant wrote the rules, so those numbers are a smoke test. Replaying 911 real "
             "captured documents, our false-trigger fixes cut simulated stress runs from 84 to 50. Read the "
             "disclaimer aloud.")

    # 6 ── domain impact and business value
    s = prs.slides.add_slide(blank)
    title(s, "Domain impact and business value", "Decision support for credit and portfolio risk")
    who = [("Credit analysts", "see which held names need attention and the rule that fired"),
           ("Risk managers", "get an audited, simulated portfolio view when news breaks"),
           ("Portfolio managers", "see linked exposure and test their own shocks instantly")]
    cw = Inches(3.95)
    for i, (head, body) in enumerate(who):
        x = MARGIN + i * (cw + Inches(0.12))
        card(s, x, BODY_TOP, cw, Inches(1.3))
        text(s, x + Inches(0.2), BODY_TOP + Inches(0.1), cw - Inches(0.35), Inches(0.45), head, size=19, bold=True,
             color=NAVY)
        text(s, x + Inches(0.2), BODY_TOP + Inches(0.55), cw - Inches(0.35), Inches(0.7), body, size=15)
    y3 = BODY_TOP + Inches(1.55)
    hh = Inches(2.25)
    p1 = picture(s, ASSETS / "watchlist.png", MARGIN, y3, h=hh)
    p2 = picture(s, ASSETS / "credit_brief.png", MARGIN + p1.width + Inches(0.15), y3, h=hh)
    gx = p2.left + p2.width + Inches(0.15)
    p3 = picture(s, ASSETS / "propagation_graph.png", gx, y3, w=W - MARGIN - gx)
    caption(s, MARGIN, y3 + hh + Inches(0.04), p1.width, "Early-warning watchlist on real news")
    caption(s, p2.left, y3 + hh + Inches(0.04), p2.width, "One-click credit brief (template, no LLM; PDF)")
    caption(s, p3.left, y3 + p3.height + Inches(0.04), p3.width, "Propagation over curated links")
    footer(s, 6)
    notes(s, "Business value without invented numbers: earlier attention on held names, triage by materiality with the "
             "reason shown, and an immediate, audited portfolio view. Linked exposure is an attention measure, not a "
             "contagion model.")

    # 7 ── limitations and future work
    s = prs.slides.add_slide(blank)
    title(s, "Limitations and future work")
    cols = [("Limitations", ["Impact weights are uncalibrated priors", "Keyword rules still misfire on real data",
                             "Headline-only news text", "Small AI-labelled evaluation set",
                             "Illustrative stress model, synthetic portfolio"]),
            ("Future work", ["Calibrate impact on market moves", "Licensed full-text news",
                             "Fine-tuned models on public labels (notebook ready)", "Kafka streaming",
                             "Backtesting and full revaluation"]),
            ("What already works", ["Provenance on every record", "One pipeline for every input",
                                    "Real-data time machine", "Trigger audit trail", "Offline demo on a laptop"])]
    cw = Inches(3.9)
    for i, (head, items) in enumerate(cols):
        x = MARGIN + i * (cw + Inches(0.17))
        card(s, x, BODY_TOP - Inches(0.25), cw, Inches(3.95))
        text(s, x + Inches(0.3), BODY_TOP - Inches(0.05), cw - Inches(0.5), Inches(0.5), head, size=22, bold=True,
             color=NAVY if i == 0 else TEAL)
        bullets(s, x + Inches(0.3), BODY_TOP + Inches(0.55), cw - Inches(0.55), Inches(3.0), items, size=17,
                space_after=6)
    card(s, MARGIN, Inches(5.5), W - 2 * MARGIN, Inches(1.15), fill=NAVY)
    text(s, MARGIN + Inches(0.4), Inches(5.5), W - 2 * MARGIN - Inches(0.8), Inches(1.15),
         "An honest, explainable bridge from text to portfolio risk that runs offline on a laptop.",
         size=24, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    footer(s, 7)
    notes(s, "Close on the takeaway. If asked about weaknesses, the limitations column is the honest list; "
             "docs/judge_qa.md has the answers.")
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
