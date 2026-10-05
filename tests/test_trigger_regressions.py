"""Regression tests for real headlines that produced false systemic stress triggers during REPLAY (2026-10-03),
plus the rules that fixed them: news-only systemic triggers, >= 2 distinct patterns for MARKET macro/geo calls,
figurative "war" guards, and the SEC != G-Sec entity fix."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from portfolio.triggers import TriggerEngine
from risk_engine.entity_resolution.resolver import EntityResolver
from risk_engine.event_classifier.rules import RuleEventClassifier
from risk_engine.impact_scoring.corroboration import CorroborationTracker
from risk_engine.impact_scoring.scorer import ImpactScorer
from risk_engine.pipeline import RiskPipeline
from risk_engine.schemas import Provenance, RawDocument, Source
from risk_engine.sentiment.finbert import SentimentEngine

# Exact texts as captured (CACHED_REAL, 2026-10-03)
WAR_ON_DATA_CENTRES = "The war on data centres is real, and it’s starting to scare markets"
FUND_NEWSLETTER = ("Quarterly Update: Q3 2026 Q3 was quieter but still constructive: profits stayed strong, inflation "
                   "remained above the Fed’s target, and we believe earnings matter more than the November election "
                   "over the next 12 months. https:// rigdencapital.com/blog/quarter ly-update-q3-2026 #news #finance")
CYPRUS_FUND = ("A stalled 20-year tourism development in Akanthou has pulled Cyprus into Turkey’s expanding "
               "investment-fund crisis, leaving local residents facing uncounted losses and authorities facing "
               "questions over leased public lands: thelevantfiles.org/2026/10/tur keys-fund-crisis-reaches-cyprus-but."
               "html #Cyprus #NorthernCyprus #Turkey #SPK #Finance #Investment #Economy")
INVASION = "Russia launches invasion as war escalates; markets plunge on sweeping sanctions"
SEC_LEGACY = "DOJ, SEC charges filed in connection with defaulted Legacy Cares bonds"
FAMILY = {"Geopolitical": "geopolitical", "Macroeconomic": "macro_rate_shock", "Credit Event": "systemic_credit"}


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(_env_file=None, sentiment_backend="lexicon")


@pytest.fixture(scope="module")
def pipe(settings) -> RiskPipeline:
    return RiskPipeline(resolver=EntityResolver(), sentiment=SentimentEngine(settings),
                        classifier=RuleEventClassifier(),
                        scorer=ImpactScorer(exposures={"IN-TATAMOTORS": 1.0, "SOV-IN": 1.0}),
                        corroboration=CorroborationTracker(6), settings=settings)


def _doc(text: str, source: Source) -> RawDocument:
    title = text if len(text) < 200 else text[:199] + "…"
    return RawDocument.build(source=source, title=title, text=text, url=f"t://{hash(text)}",
                             provenance=Provenance.CACHED_REAL)


def _systemic(settings, sig, source: str) -> list:
    t = TriggerEngine(settings, {"IN-TATAMOTORS", "SOV-IN"}, FAMILY)
    return [d for d in t.candidates(sig, source) if d.kind == "systemic"]


# ---------------------------------------------------------------- the three real misfires

def test_war_on_data_centres_is_not_geopolitical(pipe, settings):
    sig = pipe.process(_doc(WAR_ON_DATA_CENTRES, Source.GOOGLE_NEWS))
    assert sig.event_type != "Geopolitical" and sig.company != "MARKET"
    assert _systemic(settings, sig, "google_news") == []


@pytest.mark.parametrize("text", [FUND_NEWSLETTER, CYPRUS_FUND])
def test_social_posts_never_trigger_systemic_stress(pipe, settings, text):
    sig = pipe.process(_doc(text, Source.MASTODON))
    assert _systemic(settings, sig, "mastodon") == []


def test_cyprus_fund_story_is_not_a_market_macro_call(pipe):
    sig = pipe.process(_doc(CYPRUS_FUND, Source.MASTODON))
    assert not (sig.company == "MARKET" and sig.event_type == "Macroeconomic")


def test_sec_is_not_government_of_india(pipe):
    sig = pipe.process(_doc(SEC_LEGACY, Source.GOOGLE_NEWS))
    assert sig.issuer_id != "SOV-IN"


# ---------------------------------------------------------------- the rules behind the fixes

def test_market_call_needs_two_distinct_patterns(pipe):
    weak = pipe.process(_doc("Inflation worries linger for small retailers this autumn", Source.GOOGLE_NEWS))
    strong = pipe.process(_doc("Fed signals two more rate cuts as inflation cools", Source.GOOGLE_NEWS))
    assert not (weak.company == "MARKET" and weak.event_type in ("Macroeconomic", "Geopolitical"))
    assert strong.company == "MARKET" and strong.event_type == "Macroeconomic"


@pytest.mark.parametrize("text,geo", [
    ("Airlines locked in a price war over holiday fares", False),
    ("Talent war heats up as banks poach AI engineers", False),
    ("The culture war comes to corporate boardrooms", False),
    ("Russia escalates war on Ukraine as sanctions bite", True),
    ("War breaks out in the region; sanctions follow", True),
])
def test_figurative_war_guards(text, geo):
    assert (RuleEventClassifier().classify(text).primary == "Geopolitical") is geo


def test_systemic_only_from_news_sources_social_only_corroborates(pipe, settings):
    headline = "Russia launches invasion as war escalates; markets plunge on sweeping sanctions"
    sig = pipe.process(_doc(headline, Source.REDDIT))
    assert sig.company == "MARKET" and sig.impact_score >= 7.0
    assert _systemic(settings, sig, "reddit") == []  # social alone: no systemic stress
    assert _systemic(settings, sig, "mastodon") == []
    assert _systemic(settings, sig, "manual") == []
    assert len(_systemic(settings, sig, "google_news")) == 1  # same signal from a news source triggers
    assert len(_systemic(settings, sig, "gdelt")) == 1


def test_social_post_adds_corroboration_to_a_news_story(pipe, settings):
    p = RiskPipeline(resolver=EntityResolver(), sentiment=SentimentEngine(settings), classifier=RuleEventClassifier(),
                     scorer=ImpactScorer(), corroboration=CorroborationTracker(6), settings=settings)
    social = p.process(_doc("Russia launches invasion; sanctions coming, markets plunge", Source.REDDIT))
    news = p.process(_doc("Russia invades neighbour as West imposes sweeping sanctions", Source.GOOGLE_NEWS))
    assert social.corroborating_sources == 1 and news.corroborating_sources == 2  # social counted as corroboration
    assert _systemic(settings, social, "reddit") == [] and _systemic(settings, news, "google_news")


def test_api_social_signal_does_not_start_systemic_run(tmp_path):
    s = Settings(_env_file=None, db_path=tmp_path / "r.db", cache_dir=tmp_path, sentiment_backend="lexicon",
                 log_dir=tmp_path / "logs")
    with TestClient(create_app(s)) as c:
        c.post("/analyze", json={"source": "reddit", "text": INVASION})
        assert c.get("/stress-runs").json()["runs"] == []
        c.post("/analyze", json={"source": "gdelt",
                                 "text": "Invasion confirmed as troops cross border; sweeping sanctions imposed"})
        runs = c.get("/stress-runs").json()["runs"]
        assert len(runs) == 1 and runs[0]["scenario"].startswith("geopolitical_")
