"""Text cleaning and language check. Pure functions; no network."""

from __future__ import annotations

import html
import re
from functools import lru_cache

from risk_engine.logging_setup import get_logger
from risk_engine.schemas import RawDocument

log = get_logger(__name__)

MAX_TEXT_CHARS = 5000
MIN_CHARS_FOR_LANG_CHECK = 25
NON_EN_REJECT_PROB = 0.90

# Inline tags (Mastodon hashtag links: <a>#<span>Finance</span></a>) vanish; block tags become spaces.
_INLINE_TAG_RE = re.compile(r"</?(?:a|span|b|i|em|strong)\b[^>]*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+")
_WS_RE = re.compile(r"\s+")
# zero-width space/joiners/marks (U+200B-U+200F), word joiner (U+2060), BOM (U+FEFF)
_ZERO_WIDTH_RE = re.compile("[" + chr(0x200B) + "-" + chr(0x200F) + chr(0x2060) + chr(0xFEFF) + "]")
# Reddit RSS bodies end with "submitted by /u/name [link] [comments]"
_REDDIT_FOOTER_RE = re.compile(r"submitted by\s+/u/\S+.*$", re.IGNORECASE | re.DOTALL)


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    s = html.unescape(raw)
    s = _INLINE_TAG_RE.sub("", s)
    s = _TAG_RE.sub(" ", s)
    s = html.unescape(s)  # double-escaped feeds
    s = _REDDIT_FOOTER_RE.sub(" ", s)
    s = _URL_RE.sub(" ", s)
    s = _ZERO_WIDTH_RE.sub("", s)
    s = s.replace("[link]", " ").replace("[comments]", " ")
    return _WS_RE.sub(" ", s).strip()


_MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9_][\w.-]*(?:@[\w.-]+)?")
_HASHTAG_SPACING_RE = re.compile(r"(?<!\S)# (?=\w)")


def scrub_mentions(text: str) -> str:
    """Privacy: replace @handles (incl. @user@instance) in social text with a neutral token."""
    return _MENTION_RE.sub("@user", text)


def repair_hashtag_spacing(text: str) -> str:
    """Older captures rendered Mastodon hashtags as '# Finance'; restore '#Finance'."""
    return _HASHTAG_SPACING_RE.sub("#", text)


def strip_publisher_suffix(title: str, publisher: str | None) -> str:
    """Google News titles look like 'Headline - Publisher'. Remove the suffix when it matches."""
    if publisher:
        for sep in (" - ", " | ", " – "):
            suffix = f"{sep}{publisher}"
            if title.endswith(suffix):
                return title[: -len(suffix)].strip()
    return title


def make_title(text: str, max_chars: int = 200) -> str:
    """Social posts have no title: use the first line/sentence, cut on a word boundary."""
    first = re.split(r"(?<=[.!?])\s|\n", text.strip(), maxsplit=1)[0]
    if len(first) <= max_chars:
        return first
    cut = first[:max_chars].rsplit(" ", 1)[0]
    return (cut or first[:max_chars]) + "…"


@lru_cache(maxsize=1)
def _langdetect():
    from langdetect import DetectorFactory, detect_langs

    DetectorFactory.seed = 0  # deterministic
    return detect_langs


def is_english(text: str) -> bool:
    """Reject only when confident the text is NOT English; short texts (tickers, slang) pass."""
    letters = re.sub(r"[$#@]\w+|[^A-Za-zÀ-￿ ]", " ", text)
    if len(letters.strip()) < MIN_CHARS_FOR_LANG_CHECK:
        return True
    try:
        langs = _langdetect()(letters)
    except Exception:  # langdetect raises on feature-less input
        return True
    top = langs[0]
    return not (top.lang != "en" and top.prob >= NON_EN_REJECT_PROB)


def clean_document(doc: RawDocument) -> RawDocument | None:
    """Return a cleaned copy, or None if the document is empty or non-English after cleaning."""
    title = strip_publisher_suffix(clean_text(doc.title), doc.publisher)
    text = clean_text(doc.text)[:MAX_TEXT_CHARS]
    if doc.text.strip() == doc.title.strip():
        text = title
    if not title and text:
        title = make_title(text)
    if not title:
        log.debug("dropping empty document %s", doc.doc_id)
        return None
    if not is_english(f"{title}. {text}" if text != title else title):
        log.debug("dropping non-English document %s: %s", doc.doc_id, title[:60])
        return None
    # doc_id is kept: it identifies the document as captured, which is what exact dedup needs.
    return doc.model_copy(update={"title": title, "text": text or title})
