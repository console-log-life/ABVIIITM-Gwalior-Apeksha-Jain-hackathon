"""Entity resolution (spec 6.1).

Order: (1) cashtags  (2) alias dictionary (ambiguous aliases need a context keyword or ticker hint)
       (3) spaCy ORG entities matched to names/aliases  (4) rapidfuzz token_set_ratio >= 88 on ORG spans
       (5) document ticker hint  (6) MARKET for Geopolitical/Macroeconomic events, else UNRESOLVED.

Guard on (4): token_set_ratio is 100 whenever one token set is a subset of the other ("Bank" vs "Bank of
America"), so fuzzy matching is only applied to spaCy ORG spans, and the span must share a non-generic token
with the candidate name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from rapidfuzz import fuzz

from risk_engine.logging_setup import get_logger

log = get_logger(__name__)
UNIVERSE_YAML = Path(__file__).with_name("universe.yaml")
FUZZY_THRESHOLD = 88
MARKET = "MARKET"
UNRESOLVED = "UNRESOLVED"
MARKET_EVENTS = {"Geopolitical", "Macroeconomic"}

CASHTAG_RE = re.compile(r"(?<![A-Za-z0-9$])\$([A-Z]{1,5}(?:\.[A-Z])?)(?![A-Za-z0-9])")
CASHTAG_STOPLIST = {"US", "USD", "INR", "EUR", "GBP", "JPY", "CAD", "AUD", "BTC", "ETH", "A", "I"}
GENERIC_TOKENS = {
    "bank", "group", "inc", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "holdings", "the",
    "of", "and", "industries", "motors", "enterprises", "financial", "india", "state", "states", "united",
    "government", "platforms", "services", "international", "global", "capital", "securities", "us", "u", "s",
}
_SUFFIX_RE = re.compile(r"\b(inc|corp|corporation|co|ltd|limited|plc|llc|sa|ag|nv)\b\.?", re.I)
_PUNCT_RE = re.compile(r"[^\w\s&]")


def normalise_name(s: str) -> str:
    s = _PUNCT_RE.sub(" ", s.casefold())
    s = _SUFFIX_RE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _word_re(phrases: list[str], flags: int = re.I) -> re.Pattern | None:
    phrases = [p for p in phrases if p]
    if not phrases:
        return None
    alt = "|".join(re.escape(p) for p in sorted(phrases, key=len, reverse=True))
    return re.compile(rf"(?<![A-Za-z0-9])(?:{alt})(?![A-Za-z0-9])", flags)


@dataclass(frozen=True)
class Issuer:
    issuer_id: str
    name: str
    ticker: str | None
    sector: str
    country: str
    rating_bucket: str
    type: str
    aliases: tuple[str, ...]
    ambiguous_aliases: tuple[str, ...]
    context: tuple[str, ...]


@dataclass
class Resolution:
    kind: str  # ISSUER | EXTERNAL_TICKER | MARKET | UNRESOLVED
    company: str
    method: str
    issuer: Issuer | None = None
    ticker: str | None = None
    surface: str | None = None
    relation: str | None = None  # "supplier" when the text is about a supplier of this issuer
    mentions: list[str] = field(default_factory=list)  # all issuer_ids found

    @property
    def issuer_id(self) -> str | None:
        return self.issuer.issuer_id if self.issuer else None

    @property
    def is_resolved(self) -> bool:
        return self.kind in ("ISSUER", "EXTERNAL_TICKER")

    def finalize(self, event_type: str) -> Resolution:
        """Step 5: nothing resolved + market-wide event type -> MARKET."""
        weak = self.method == "ticker-hint"  # only the search query suggested it; text names no company
        if (not self.is_resolved or weak) and event_type in MARKET_EVENTS:
            return Resolution(kind=MARKET, company=MARKET, method="market-event", mentions=self.mentions)
        return self


@dataclass
class _Hit:
    issuer: Issuer | None
    ticker: str | None
    surface: str
    start: int
    method: str


class EntityResolver:
    def __init__(self, universe_path: Path = UNIVERSE_YAML, use_spacy: bool = True):
        data = yaml.safe_load(Path(universe_path).read_text(encoding="utf-8"))
        self.issuers: list[Issuer] = [
            Issuer(
                issuer_id=i["issuer_id"], name=i["name"], ticker=i.get("ticker"), sector=i["sector"],
                country=i["country"], rating_bucket=i["rating_bucket"], type=i.get("type", "corporate"),
                aliases=tuple(i.get("aliases") or ()), ambiguous_aliases=tuple(i.get("ambiguous_aliases") or ()),
                context=tuple(str(c).lower() for c in (i.get("context") or ())),
            )
            for i in data["issuers"]
        ]
        self.by_id = {i.issuer_id: i for i in self.issuers}
        self.by_ticker: dict[str, Issuer] = {}
        for i in self.issuers:
            if i.ticker:
                self.by_ticker[i.ticker.upper()] = i
                self.by_ticker.setdefault(i.ticker.split(".")[0].upper(), i)
        self._general_ctx = _word_re([str(c) for c in data.get("context_keywords") or []])
        self._alias_re = {i.issuer_id: _word_re([i.name, *i.aliases]) for i in self.issuers}
        self._ambig_re = {i.issuer_id: _word_re(list(i.ambiguous_aliases)) for i in self.issuers}
        self._issuer_ctx = {i.issuer_id: _word_re(list(i.context)) for i in self.issuers}
        self._names: list[tuple[str, Issuer, bool]] = []  # (normalised name/alias, issuer, ambiguous)
        for i in self.issuers:
            for n in (i.name, *i.aliases):
                self._names.append((normalise_name(n), i, False))
            for n in i.ambiguous_aliases:
                self._names.append((normalise_name(n), i, True))
        self._ambig_tokens = {
            i.issuer_id: {t for a in i.ambiguous_aliases for t in normalise_name(a).split()} for i in self.issuers
        }
        self.use_spacy = use_spacy

    # ------------------------------------------------------------------ steps
    def _cashtags(self, text: str) -> list[_Hit]:
        hits = []
        for m in CASHTAG_RE.finditer(text):
            sym = m.group(1)
            if sym in CASHTAG_STOPLIST:
                continue
            iss = self.by_ticker.get(sym)
            hits.append(_Hit(iss, iss.ticker if iss else sym, m.group(0), m.start(), "cashtag"))
        return hits

    def _has_context(self, issuer: Issuer, text: str, hint_ticker: str | None) -> bool:
        if hint_ticker and self.by_ticker.get(hint_ticker.upper()) is issuer:
            return True
        if self._general_ctx and self._general_ctx.search(text):
            return True
        ctx = self._issuer_ctx.get(issuer.issuer_id)
        return bool(ctx and ctx.search(text))

    def _aliases(self, text: str, hint_ticker: str | None) -> list[_Hit]:
        hits = []
        for iss in self.issuers:
            rx = self._alias_re[iss.issuer_id]
            m = rx.search(text) if rx else None
            if m:
                hits.append(_Hit(iss, iss.ticker, m.group(0), m.start(), "alias"))
                continue
            rx = self._ambig_re[iss.issuer_id]
            for m in (rx.finditer(text) if rx else ()):
                # Ambiguous brand words must be capitalised (proper noun) AND have context or a ticker hint.
                if m.group(0)[0].isupper() and self._has_context(iss, text, hint_ticker):
                    hits.append(_Hit(iss, iss.ticker, m.group(0), m.start(), "alias+context"))
                    break
        return hits

    def _match_org(self, org: str, text: str, hint_ticker: str | None) -> tuple[Issuer, str] | None:
        norm = normalise_name(org)
        if not norm:
            return None
        distinctive = set(norm.split()) - GENERIC_TOKENS
        best: tuple[float, Issuer, bool, str] | None = None
        for cand, iss, ambiguous in self._names:
            if cand == norm:
                score, method = 100.0, "spacy_org"
            else:
                # every distinctive token of the candidate must appear in the ORG span: "SEC" must not match the alias
                # "G-Sec" (Government of India), and "Reliance" must not match "Reliance Jio"
                cand_distinctive = set(cand.split()) - GENERIC_TOKENS
                if not cand_distinctive or not cand_distinctive <= distinctive:
                    continue
                score = fuzz.token_set_ratio(norm, cand)
                if score < FUZZY_THRESHOLD:
                    continue
                method = "fuzzy"
            # "Apple Inc." normalises to "apple", and "Reliance" fuzzy-matches "Reliance Jio": whenever the span's
            # distinctive words are only ambiguous brand words, the match needs context like any ambiguous alias.
            ambiguous = ambiguous or distinctive <= self._ambig_tokens[iss.issuer_id]
            if ambiguous and not self._has_context(iss, text, hint_ticker):
                continue
            if best is None or score > best[0]:
                best = (score, iss, ambiguous, method)
        return (best[1], best[3]) if best else None

    def _spacy_orgs(self, text: str, hint_ticker: str | None) -> list[_Hit]:
        nlp = _spacy_nlp() if self.use_spacy else None
        if nlp is None:
            return []
        hits = []
        for ent in nlp(text[:2000]).ents:
            if ent.label_ != "ORG":
                continue
            found = self._match_org(ent.text, text, hint_ticker)
            if found:
                hits.append(_Hit(found[0], found[0].ticker, ent.text, ent.start_char, found[1]))
        return hits

    def _relation(self, surface: str, text: str) -> str | None:
        s = re.escape(surface)
        pat = rf"(?:{s}(?:'s|’s)?\s+(?:\w+\s+)?suppliers?\b|suppliers?\s+(?:to|for)\s+{s}(?![A-Za-z0-9]))"
        return "supplier" if re.search(pat, text, re.I) else None

    # ------------------------------------------------------------------ public
    def resolve(self, title: str, text: str | None = None, hint_ticker: str | None = None) -> Resolution:
        full = title if not text or text.strip() == title.strip() else f"{title}. {text}"
        hits = self._cashtags(full) + self._aliases(full, hint_ticker)
        if not hits:
            hits = self._spacy_orgs(full, hint_ticker)
        issuer_ids = list(dict.fromkeys(h.issuer.issuer_id for h in hits if h.issuer))

        if hits:
            hint_iss = self.by_ticker.get(hint_ticker.upper()) if hint_ticker else None
            chosen = next((h for h in hits if hint_iss and h.issuer is hint_iss), None)
            if chosen is None:  # prefer universe issuers, then the earliest mention (headline subject)
                chosen = min(hits, key=lambda h: (h.issuer is None, h.start))
            if chosen.issuer:
                return Resolution("ISSUER", chosen.issuer.name, chosen.method, chosen.issuer, chosen.issuer.ticker,
                                  chosen.surface, self._relation(chosen.surface, full), issuer_ids)
            return Resolution("EXTERNAL_TICKER", chosen.ticker or chosen.surface, chosen.method, None,
                              chosen.ticker, chosen.surface, None, issuer_ids)

        if hint_ticker:
            iss = self.by_ticker.get(hint_ticker.upper())
            if iss:
                return Resolution("ISSUER", iss.name, "ticker-hint", iss, iss.ticker, None, None, [iss.issuer_id])
        return Resolution(UNRESOLVED, UNRESOLVED, "none")


@lru_cache(maxsize=1)
def _spacy_nlp():
    try:
        import spacy

        return spacy.load("en_core_web_sm", exclude=["lemmatizer", "parser"])
    except Exception as exc:  # spaCy model missing -> steps 3/4 are skipped, logged once
        log.warning("spaCy en_core_web_sm unavailable, ORG step disabled: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_resolver() -> EntityResolver:
    return EntityResolver()
