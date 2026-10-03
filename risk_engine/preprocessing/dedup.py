"""Duplicate detection.

1. Exact: doc_id (sha1 of source+url+title) or sha1 of the normalised title within the same source.
2. Near-duplicate: rapidfuzz ratio >= NEAR_DUP_THRESHOLD (default 92) on normalised titles.
   - same source          -> dropped (syndicated copy / re-post)
   - different source     -> KEPT and marked, because two independent sources reporting the same
                             story is exactly the corroboration signal the impact scorer needs.
"""

from __future__ import annotations

import hashlib
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from rapidfuzz import fuzz, process

from risk_engine.schemas import RawDocument

MIN_CHARS_FOR_FUZZY = 25  # short social posts ("$AAPL 🚀") only get exact matching


class DedupVerdict(str, Enum):
    NEW = "new"
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE_SAME_SOURCE = "near_duplicate_same_source"
    CROSS_SOURCE_MATCH = "cross_source_match"  # kept

    @property
    def keep(self) -> bool:
        return self in (DedupVerdict.NEW, DedupVerdict.CROSS_SOURCE_MATCH)


@dataclass(frozen=True)
class DedupResult:
    verdict: DedupVerdict
    matched_doc_id: str | None = None
    score: float | None = None


_NORM_RE = re.compile(r"[^a-z0-9$ ]+")


def normalise_title(title: str) -> str:
    return re.sub(r"\s+", " ", _NORM_RE.sub(" ", title.lower())).strip()


def _title_hash(source: str, norm: str) -> str:
    return hashlib.sha1(f"{source}|{norm}".encode()).hexdigest()


class Deduplicator:
    def __init__(self, threshold: int = 92, max_titles: int = 5_000):
        self.threshold = threshold
        self._ids: set[str] = set()
        self._hashes: set[str] = set()
        self._recent: deque[tuple[str, str, str]] = deque(maxlen=max_titles)  # (norm_title, source, doc_id)

    def __len__(self) -> int:
        return len(self._ids)

    def check(self, doc: RawDocument) -> DedupResult:
        src = doc.source.value
        norm = normalise_title(doc.title)
        if doc.doc_id in self._ids or _title_hash(src, norm) in self._hashes:
            return DedupResult(DedupVerdict.EXACT_DUPLICATE)
        if len(norm) < MIN_CHARS_FOR_FUZZY or not self._recent:
            return DedupResult(DedupVerdict.NEW)

        choices = [t[0] for t in self._recent]
        best_cross: DedupResult | None = None
        for _match, score, idx in process.extract(norm, choices, scorer=fuzz.ratio,
                                                   score_cutoff=self.threshold, limit=10):
            _, other_src, other_id = self._recent[idx]
            if other_src == src:
                return DedupResult(DedupVerdict.NEAR_DUPLICATE_SAME_SOURCE, other_id, score)
            if best_cross is None:
                best_cross = DedupResult(DedupVerdict.CROSS_SOURCE_MATCH, other_id, score)
        return best_cross or DedupResult(DedupVerdict.NEW)

    def add(self, doc: RawDocument) -> None:
        norm = normalise_title(doc.title)
        self._ids.add(doc.doc_id)
        self._hashes.add(_title_hash(doc.source.value, norm))
        if len(norm) >= MIN_CHARS_FOR_FUZZY:
            self._recent.append((norm, doc.source.value, doc.doc_id))

    def seed(self, docs: Iterable[RawDocument]) -> None:
        """Pre-load already-seen documents (e.g. existing cache) without returning them."""
        for d in docs:
            self.add(d)

    def filter(self, docs: Iterable[RawDocument]) -> tuple[list[RawDocument], dict[str, int]]:
        kept: list[RawDocument] = []
        counts = {v.value: 0 for v in DedupVerdict}
        for d in docs:
            res = self.check(d)
            counts[res.verdict.value] += 1
            if res.verdict.keep:
                self.add(d)
                kept.append(d)
        return kept, counts
