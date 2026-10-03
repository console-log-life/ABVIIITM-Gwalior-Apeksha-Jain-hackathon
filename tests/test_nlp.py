"""M2 NLP core: entity resolution, event rules, lexicon sentiment, label mapping, scorer, corroboration,
and the full pipeline (lexicon backend, so it runs without model weights)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from risk_engine.entity_resolution.resolver import EntityResolver
from risk_engine.event_classifier.rules import RuleEventClassifier
from risk_engine.impact_scoring.corroboration import CorroborationTracker
from risk_engine.impact_scoring.scorer import ImpactInput, ImpactScorer
from risk_engine.pipeline import DocumentRejected, RiskPipeline
from risk_engine.schemas import Provenance, RawDocument, Source, SourceType
from risk_engine.sentiment.finbert import SentimentEngine, aggregate, map_logits_to_probs, segments_for
from risk_engine.sentiment.lexicon_fallback import lexicon_probs


@pytest.fixture(scope="module")
def resolver() -> EntityResolver:
    return EntityResolver()


@pytest.fixture(scope="module")
def classifier() -> RuleEventClassifier:
    return RuleEventClassifier()


# ---------------------------------------------------------------- entity resolution

@pytest.mark.parametrize("text", ["Apple pie recipe for the holidays", "The best apple crumble ever",
                                  "Reliance on imports rises", "Harrison Ford stars in new film",
                                  "Amazon rainforest fires spread"])
def test_ambiguous_words_do_not_resolve(resolver, text):
    assert resolver.resolve(text).kind == "UNRESOLVED"


@pytest.mark.parametrize("text,ticker,method", [
    ("Apple shares fall after iPhone sales miss", "AAPL", "alias+context"),
    ("$AAPL breaking out to new highs", "AAPL", "cashtag"),
    ("Moody's downgrades Tata Motors", "TATAMOTORS.NS", "alias"),
    ("Reliance Industries Q2 profit jumps", "RELIANCE.NS", "alias"),
    ("Amazon shares jump on AWS growth", "AMZN", "alias"),
])
def test_resolves_universe_issuers(resolver, text, ticker, method):
    r = resolver.resolve(text)
    assert r.kind == "ISSUER" and r.ticker == ticker and r.method == method


def test_ticker_hint_unlocks_ambiguous_alias(resolver):
    assert resolver.resolve("Apple holiday outlook", hint_ticker="AAPL").ticker == "AAPL"


def test_supplier_relation(resolver):
    r = resolver.resolve("Foxconn, Apple's key supplier, halts production")
    assert r.ticker == "AAPL" and r.relation == "supplier"


def test_unknown_company_is_unresolved_and_market_events_become_market(resolver):
    r = resolver.resolve("Acme Widgets files for bankruptcy")
    assert r.kind == "UNRESOLVED" and r.company == "UNRESOLVED"
    assert r.finalize("Credit Event").company == "UNRESOLVED"
    assert r.finalize("Geopolitical").company == "MARKET"


def test_ticker_hint_alone_yields_to_market_for_macro(resolver):
    r = resolver.resolve("Fed signals two more rate cuts", hint_ticker="AAPL")
    assert r.method == "ticker-hint" and r.finalize("Macroeconomic").company == "MARKET"


def test_external_cashtag(resolver):
    r = resolver.resolve("$SEIC forms hammer pattern")
    assert r.kind == "EXTERNAL_TICKER" and r.ticker == "SEIC" and r.issuer is None


# ---------------------------------------------------------------- event rules

@pytest.mark.parametrize("text,expected", [
    ("Russia launches invasion as war escalates; sanctions follow", "Geopolitical"),
    ("Moody's downgrades Example Corp to junk after missed coupon payment", "Credit Event"),
    ("Microsoft agrees to acquire gaming studio in $10bn takeover", "M&A"),
    ("SEC opens antitrust probe into chipmaker", "Regulatory"),
    ("Fed signals rate cuts as inflation cools", "Macroeconomic"),
    ("Apple unveils new iPhone lineup", "Product Launch"),
    ("Company beats earnings estimates, raises guidance", "Earnings"),
    ("Shareholders file class action lawsuit against bank", "Litigation"),
    ("Chip shortage forces production halt at plant", "Supply Chain"),
    ("CEO steps down amid succession questions", "Management"),
    ("Nice weather this weekend", "Other"),
])
def test_event_classes(classifier, text, expected):
    assert classifier.classify(text).primary == expected


def test_secondary_and_evidence(classifier):
    r = classifier.classify("Moody's downgrades Tata Motors to junk as regulators open probe")
    assert r.primary == "Credit Event" and r.secondary == "Regulatory"  # credit 6 vs regulatory 5 (>= 60%)
    assert "downgrades" in r.evidence and "probe" in r.evidence
    r2 = classifier.classify("Moody's downgrades Tata Motors as regulators open probe")  # credit 4 vs reg 5
    assert r2.primary == "Regulatory" and r2.secondary == "Credit Event"


def test_by_default_is_not_a_credit_default(classifier):
    assert classifier.classify("Settings are enabled by default").primary == "Other"


def test_intensifiers_case_sensitive_may(classifier):
    up = classifier.classify("Company may default on bonds")
    month = classifier.classify("Company defaults on bonds in May")
    assert up.intensifier_adj == pytest.approx(0.05)  # +0.15 default, -0.10 'may'
    assert month.intensifier_adj == pytest.approx(0.15)


# ---------------------------------------------------------------- sentiment

def test_lexicon_polarity_and_negation():
    assert lexicon_probs("Shares surge after strong results")["positive"] > 0.5
    assert lexicon_probs("Shares plunge after profit warning")["negative"] > 0.5
    neutral = lexicon_probs("The company held its annual meeting on Tuesday")
    assert neutral["neutral"] == 1.0
    negated = lexicon_probs("Company did not default on its bonds")
    assert negated["positive"] > 0  # negation flips "default"


def test_lexicon_engine_caps_confidence():
    eng = SentimentEngine(Settings(_env_file=None, sentiment_backend="lexicon"))
    r = eng.analyze("Bank collapses into bankruptcy amid fraud probe")
    assert r.model == "lexicon-fallback" and r.confidence <= 0.5 and r.label == "Negative"
    assert eng.status()["loaded"] is False


def test_label_mapping_uses_id2label_not_index_order():
    row = [0.7, 0.2, 0.1]
    assert map_logits_to_probs(row, {0: "positive", 1: "negative", 2: "neutral"})["positive"] == 0.7
    assert map_logits_to_probs(row, {0: "neutral", 1: "positive", 2: "negative"})["neutral"] == 0.7
    assert map_logits_to_probs(row, {"0": "NEGATIVE", "1": "Neutral", "2": "Positive"})["negative"] == 0.7
    with pytest.raises(ValueError):
        map_logits_to_probs(row, {0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"})


def test_segments_and_weighted_aggregation():
    segs = segments_for("Title here", "Title here. First sentence. Second one! Third?")
    assert segs[0] == ("Title here", 2.0) and len(segs) == 4
    agg = aggregate([{"positive": 1.0, "negative": 0.0, "neutral": 0.0},
                     {"positive": 0.0, "negative": 1.0, "neutral": 0.0}], [2.0, 1.0])
    assert agg["positive"] == pytest.approx(2 / 3)


# ---------------------------------------------------------------- scorer

def _inp(**kw) -> ImpactInput:
    base = dict(event_type="Credit Event", intensifier_adj=0.0, sentiment_score=-0.8, confidence=0.9,
                entity_kind="ISSUER", issuer_id="US-AAPL", company="Apple Inc.", source="google_news",
                corroborating_sources=1)
    return ImpactInput(**{**base, **kw})


def test_impact_bounded_on_grid():
    w = ImpactScorer().w
    for vals in itertools.product([0.0, 0.5, 1.0], repeat=5):
        s = ImpactScorer.combine(dict(zip("EMXRQ", vals, strict=True)), w)
        assert 1.0 <= s <= 10.0
    assert ImpactScorer.combine(dict.fromkeys("EMXRQ", 1.0), w) == 10.0
    assert ImpactScorer.combine(dict.fromkeys("EMXRQ", 0.0), w) == 1.0


@pytest.mark.parametrize("factor", list("EMXRQ"))
def test_impact_monotonic_in_each_factor(factor):
    w = ImpactScorer().w
    base = dict.fromkeys("EMXRQ", 0.5)
    scores = [ImpactScorer.combine({**base, factor: v}, w) for v in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert scores == sorted(scores) and scores[-1] > scores[0]


def test_factor_definitions():
    sc = ImpactScorer(exposures={"US-AAPL": 100.0, "US-JPM": 50.0})
    assert sc.factor_m(-0.8) == pytest.approx(0.8) and sc.factor_m(0.8) == pytest.approx(0.48)
    assert sc.factor_x("MARKET", None) == 1.0
    assert sc.factor_x("ISSUER", "US-AAPL") == pytest.approx(1.0)
    assert sc.factor_x("ISSUER", "US-JPM") == pytest.approx(0.7)
    assert sc.factor_x("ISSUER", "US-MSFT") == 0.3 and sc.factor_x("UNRESOLVED", None) == 0.1
    assert sc.factor_r("reddit", 1) == 0.4 and sc.factor_r("google_news", 3) == pytest.approx(1.0)
    assert sc.factor_q(0.5) == pytest.approx(0.8)
    assert sc.factor_e("Credit Event", 0.25) == 1.0


def test_risk_levels_and_texts():
    sc = ImpactScorer(exposures={"US-AAPL": 1.0})
    assert [sc.risk_level(x) for x in (3.9, 4.0, 6.9, 7.0, 8.4, 8.5)] == \
        ["Low", "Medium", "Medium", "High", "High", "Critical"]
    r = sc.score(_inp())
    assert r.held and "held issuer" in r.business_implication and r.reason.startswith(f"Impact {r.score}")


# ---------------------------------------------------------------- corroboration

def test_corroboration_rules():
    t0 = datetime(2026, 10, 3, 12, tzinfo=UTC)
    tr = CorroborationTracker(6)
    assert tr.count_and_add("US-AAPL", "Credit Event", "google_news", t0, ["downgrade"]) == 1
    assert tr.count_and_add("US-AAPL", "Credit Event", "google_news", t0, ["downgrade"]) == 1  # same source
    assert tr.count_and_add("US-AAPL", "Credit Event", "reddit", t0 + timedelta(hours=2), ["junk"]) == 2
    # +9 h: both earlier observations (t0, t0+2h) are more than 6 h away -> only itself
    assert tr.count_and_add("US-AAPL", "Credit Event", "gdelt", t0 + timedelta(hours=9), ["x"]) == 1
    assert tr.count_and_add("US-AAPL", "Earnings", "gdelt", t0, ["x"]) == 1  # different event
    assert tr.count_and_add(None, "Credit Event", "gdelt", t0, ["x"]) == 1  # unresolved
    assert tr.count_and_add("MARKET", "Geopolitical", "google_news", t0, ["sanctions"]) == 1
    assert tr.count_and_add("MARKET", "Geopolitical", "gdelt", t0, ["ceasefire"]) == 1  # no shared evidence
    assert tr.count_and_add("MARKET", "Geopolitical", "reddit", t0, ["sanctions", "war"]) == 2


# ---------------------------------------------------------------- full pipeline (lexicon backend)

@pytest.fixture
def pipe(resolver, classifier) -> RiskPipeline:
    s = Settings(_env_file=None, sentiment_backend="lexicon")
    return RiskPipeline(resolver=resolver, sentiment=SentimentEngine(s), classifier=classifier,
                        scorer=ImpactScorer(exposures={"US-AAPL": 100.0, "IN-TATAMOTORS": 40.0}),
                        corroboration=CorroborationTracker(6), settings=s)


def _doc(title: str, source: Source = Source.GOOGLE_NEWS, **kw) -> RawDocument:
    return RawDocument.build(source=source, title=title, provenance=Provenance.SYNTHETIC,
                             source_type=SourceType.NEWS, url=f"t://{title}", **kw)


def test_pipeline_positive_negative_neutral(pipe):
    pos, neg, neu = pipe.process_batch([_doc("Apple shares surge after strong iPhone sales beat estimates"),
                                        _doc("Tata Motors shares plunge after profit warning"),
                                        _doc("Infosys to hold annual general meeting on Tuesday")])
    assert pos.sentiment_label == "Positive" and pos.sentiment_score > 0 and pos.ticker == "AAPL"
    assert neg.sentiment_label == "Negative" and neg.sentiment_score < 0
    assert neu.sentiment_label == "Neutral" and -1 <= neu.sentiment_score <= 1


def test_pipeline_geopolitical_market_high_impact(pipe):
    s = pipe.process(_doc("Russia launches invasion as war escalates; markets plunge on sanctions fears"))
    assert s.event_type == "Geopolitical" and s.company == "MARKET" and s.ticker is None
    assert s.impact_factors.X == 1.0 and s.impact_score >= 7.0 and s.risk_level in ("High", "Critical")


def test_pipeline_credit_event_on_held_issuer(pipe):
    s = pipe.process(_doc("Moody's downgrades Tata Motors to junk"))
    assert s.event_type == "Credit Event" and s.issuer_id == "IN-TATAMOTORS"
    assert "held issuer" in s.business_implication and s.event_evidence


def test_pipeline_low_impact(pipe):
    s = pipe.process(_doc("Gadget maker unveils new product lineup"))
    assert s.impact_score < 4.0 and s.risk_level == "Low" and s.company == "UNRESOLVED"


def test_pipeline_scenario_uses_imitated_source_prior(pipe):
    d = RawDocument.build(source=Source.SCENARIO, title="Apple faces SEC probe", provenance=Provenance.SYNTHETIC,
                          source_type=SourceType.NEWS, imitated_source=Source.REDDIT)
    s = pipe.process(d)
    assert s.impact_factors.R == pytest.approx(0.40) and s.provenance is Provenance.SYNTHETIC


def test_pipeline_corroboration_across_sources(pipe):
    a = pipe.process(_doc("Moody's downgrades Apple Inc to A1 on debt concerns"))
    b = pipe.process(_doc("Apple Inc. hit with Moody's downgrade", source=Source.GDELT))
    assert a.corroborating_sources == 1 and b.corroborating_sources == 2
    assert b.impact_factors.R == pytest.approx(0.85)


def test_pipeline_rejects_empty_and_non_english(pipe):
    with pytest.raises(DocumentRejected):
        pipe.process(_doc("<p>   </p>"))
    with pytest.raises(DocumentRejected):
        pipe.process(_doc("Die Europäische Zentralbank hat die Leitzinsen überraschend deutlich angehoben."))


# ---------------------------------------------------------------- real FinBERT (needs weights)

@pytest.mark.model
def test_finbert_real_model():
    eng = SentimentEngine(Settings(sentiment_backend="finbert"))
    assert set(eng._model.id2label.values()) == {"positive", "negative", "neutral"}
    pos, neg, neu = eng.analyze_many([("Company profit soars, beating all estimates", None),
                                      ("Company shares plunge after accounting fraud is revealed", None),
                                      ("The company will hold its meeting on Thursday", None)])
    assert pos.label == "Positive" and neg.label == "Negative" and neu.label == "Neutral"
    assert pos.model == "finbert" and 0 <= neg.confidence <= 1
