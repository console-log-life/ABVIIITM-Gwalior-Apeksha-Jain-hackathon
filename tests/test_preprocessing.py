from risk_engine.preprocessing.clean import clean_document, clean_text, is_english, make_title
from risk_engine.preprocessing.dedup import Deduplicator, DedupVerdict
from risk_engine.schemas import Provenance, RawDocument, Source


def _doc(source: Source, title: str, url: str | None = None, publisher: str | None = None) -> RawDocument:
    return RawDocument.build(source=source, title=title, url=url or f"https://x/{hash(title)}",
                             provenance=Provenance.LIVE, publisher=publisher)


# ---------------------------------------------------------------- cleaning

def test_clean_text_strips_html_urls_and_entities():
    assert clean_text("<p>Shares &amp; bonds fall https://t.co/x</p><br>today") == "Shares & bonds fall today"


def test_clean_document_strips_google_publisher_suffix():
    d = clean_document(_doc(Source.GOOGLE_NEWS, "Fed raises rates again - Reuters", publisher="Reuters"))
    assert d is not None and d.title == "Fed raises rates again" and d.text == d.title


def test_clean_document_drops_non_english():
    german = "Die Europäische Zentralbank hat die Leitzinsen überraschend deutlich angehoben, sagen Analysten."
    assert not is_english(german)
    assert clean_document(_doc(Source.GDELT, german)) is None


def test_short_social_text_is_not_language_rejected():
    assert is_english("$AAPL 🚀🚀 lfg")


def test_make_title_cuts_on_word_boundary():
    t = make_title("word " * 100)
    assert len(t) <= 201 and t.endswith("…")


# ---------------------------------------------------------------- dedup

def test_exact_duplicate_dropped():
    dd = Deduplicator(92)
    a = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp to junk status", url="u1")
    kept, counts = dd.filter([a, a])
    assert len(kept) == 1 and counts["exact_duplicate"] == 1


def test_same_title_different_url_same_source_is_exact_duplicate():
    dd = Deduplicator(92)
    a = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp to junk status", url="u1")
    b = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp to junk status!", url="u2")
    kept, _ = dd.filter([a, b])
    assert kept == [a]


def test_near_duplicate_same_source_dropped():
    dd = Deduplicator(92)
    a = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp to junk on rising leverage")
    b = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp. to junk on rising leverage levels")
    dd.add(a)
    assert dd.check(b).verdict is DedupVerdict.NEAR_DUPLICATE_SAME_SOURCE


def test_near_duplicate_cross_source_kept_for_corroboration():
    dd = Deduplicator(92)
    a = _doc(Source.GOOGLE_NEWS, "Moody's downgrades Example Corp to junk on rising leverage")
    b = _doc(Source.GDELT, "Moody's downgrades Example Corp to junk on rising leverage.")
    dd.add(a)
    res = dd.check(b)
    assert res.verdict is DedupVerdict.CROSS_SOURCE_MATCH and res.matched_doc_id == a.doc_id
    assert res.verdict.keep


def test_different_stories_are_new():
    dd = Deduplicator(92)
    dd.add(_doc(Source.GOOGLE_NEWS, "Apple unveils new iPhone lineup at annual event"))
    assert dd.check(_doc(Source.GOOGLE_NEWS, "Tesla recalls vehicles over braking defect")).verdict \
        is DedupVerdict.NEW


def test_short_posts_use_exact_match_only():
    dd = Deduplicator(92)
    dd.add(_doc(Source.MASTODON, "$AAPL to the moon"))
    assert dd.check(_doc(Source.MASTODON, "$AAPL to the moon!!")).verdict is DedupVerdict.EXACT_DUPLICATE
    assert dd.check(_doc(Source.MASTODON, "$AAPL to the mars")).verdict is DedupVerdict.NEW
