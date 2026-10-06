"""Fine-tuned model integration with TINY random models built on the fly (no downloads): loading, label mapping,
probability aggregation, hybrid decision rules, quantisation flag, and the import script."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from risk_engine.event_classifier.learned import HybridEventClassifier, LearnedEventModel, decide
from risk_engine.event_classifier.rules import EventResult, RuleEventClassifier
from risk_engine.model_paths import finetuned_dir

VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "fed", "rates", "apple", "iphone", "downgrade", "junk",
         "moody", "tata", "motors", "war", "earnings", "the", "a"]


def tiny_model(path: Path, labels: list[str], to_ours: dict | None = None, task: str = "event") -> Path:
    import torch
    from transformers import BertConfig, BertForSequenceClassification, BertTokenizerFast

    path.mkdir(parents=True, exist_ok=True)
    (path / "vocab.txt").write_text("\n".join(VOCAB) + "\n", encoding="utf-8")
    BertTokenizerFast(vocab_file=str(path / "vocab.txt")).save_pretrained(str(path))
    torch.manual_seed(0)
    cfg = BertConfig(vocab_size=len(VOCAB), hidden_size=16, num_hidden_layers=1, num_attention_heads=2,
                     intermediate_size=32, max_position_embeddings=64, num_labels=len(labels),
                     id2label=dict(enumerate(labels)), label2id={v: i for i, v in enumerate(labels)})
    BertForSequenceClassification(cfg).save_pretrained(str(path), safe_serialization=True)
    if to_ours is not None:
        (path / "risk_engine_labels.json").write_text(json.dumps({"task": task, "to_ours": to_ours}), encoding="utf-8")
    return path


TOPICS = {"Politics": "Geopolitical", "Macro": "Macroeconomic", "Fed | Central Banks": "Macroeconomic",
          "Earnings": "Earnings", "Markets": "Other"}


@pytest.fixture(scope="module")
def event_dir(tmp_path_factory) -> Path:
    return tiny_model(tmp_path_factory.mktemp("ev") / "event_distilroberta_ft", list(TOPICS), TOPICS)


def S(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_finetuned_dir_only_when_model_folder_exists(tmp_path, event_dir):
    assert finetuned_dir("", S()) is None
    assert finetuned_dir(str(tmp_path / "nope"), S()) is None
    assert finetuned_dir(str(event_dir), S()) == event_dir


def test_learned_model_sums_topic_probabilities_per_class(event_dir):
    m = LearnedEventModel(event_dir, S())
    assert m.classes == ["Earnings", "Geopolitical", "Macroeconomic", "Other"]
    probs = m.predict_many(["fed rates", "apple iphone earnings"])
    assert all(abs(sum(p.values()) - 1) < 1e-5 and set(p) == set(m.classes) for p in probs)


def test_learned_model_rejects_unmapped_labels(tmp_path):
    d = tiny_model(tmp_path / "bad", ["A", "B"], {"A": "Geopolitical", "B": "Not A Class"})
    with pytest.raises(ValueError, match="do not map"):
        LearnedEventModel(d, S())


def test_quantize_flag(event_dir):
    m = LearnedEventModel(event_dir, S(model_quantize_int8=True))
    assert m.quantized and abs(sum(m.predict("fed rates").values()) - 1) < 1e-5


def rule_result(primary, score, secondary=None, ev=None) -> EventResult:
    ev = ev or {primary: [primary.lower()]}
    return EventResult(primary, secondary, ev.get(primary, []), {primary: score} if primary != "Other" else {}, 0.0,
                       [], "rules", ev)


@pytest.mark.parametrize("rule, probs, expected, method", [
    # rules authoritative for Credit Event at/above the minimum score, whatever the model says
    (rule_result("Credit Event", 3.0), {"Other": 0.9, "Credit Event": 0.1}, "Credit Event",
     "hybrid:rules-authoritative"),
    # below the authoritative score -> a confident model wins
    (rule_result("Credit Event", 1.0), {"Earnings": 0.8, "Credit Event": 0.2}, "Earnings", "hybrid:model"),
    # non-authoritative class: confident model wins
    (rule_result("Product Launch", 3.0), {"M&A": 0.7, "Product Launch": 0.3}, "M&A", "hybrid:model"),
    # model unsure (< 0.6) -> rules
    (rule_result("Product Launch", 3.0), {"M&A": 0.55, "Product Launch": 0.45}, "Product Launch", "hybrid:rules"),
    # rules found nothing, model confident -> model
    (rule_result("Other", 0.0, ev={}), {"Macroeconomic": 0.95, "Other": 0.05}, "Macroeconomic", "hybrid:model"),
])
def test_hybrid_decision(rule, probs, expected, method):
    out = decide(rule, probs, S())
    assert (out.primary, out.method) == (expected, method)
    assert out.model_label == max(probs, key=probs.get) and out.model_probs


def test_hybrid_keeps_rule_evidence_and_secondary():
    r = rule_result("Product Launch", 3.0, ev={"Product Launch": ["unveils"], "M&A": ["acquire"]})
    out = decide(r, {"M&A": 0.9, "Product Launch": 0.1}, S())
    assert out.primary == "M&A" and out.secondary == "Product Launch"
    assert out.evidence == ["acquire", "unveils"]  # rule evidence stays visible for explainability


def test_hybrid_classifier_is_a_drop_in_for_the_triggers(event_dir):
    rules = RuleEventClassifier()
    h = HybridEventClassifier(rules, LearnedEventModel(event_dir, S()), S())
    assert h.market_min_patterns == rules.market_min_patterns
    assert h.class_evidence_count("Geopolitical", ["war", "sanctions"]) == 2
    res = h.classify("Moody's downgrades Tata Motors to junk")
    assert res.primary == "Credit Event" and res.method == "hybrid:rules-authoritative" and res.evidence


def test_finetuned_sentiment_model_loads_from_folder(tmp_path):
    from risk_engine.sentiment.finbert import _FinBertModel

    d = tiny_model(tmp_path / "sentiment_finbert_ft", ["positive", "negative", "neutral"])
    m = _FinBertModel(S(model_sentiment_path=str(d)))
    assert m.variant == "fine-tuned" and m.source == str(d)
    p = m.predict(["fed rates"])[0]
    assert set(p) == {"positive", "negative", "neutral"} and abs(sum(p.values()) - 1) < 1e-5


def test_import_script_installs_and_verifies(tmp_path, monkeypatch, event_dir):
    import sys

    from app.config import PROJECT_ROOT

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import import_trained_models as imp

    stage = tmp_path / "zip" / "out"
    tiny_model(stage / "trained_models" / "sentiment_finbert_ft", ["positive", "negative", "neutral"],
               {"positive": "Positive", "negative": "Negative", "neutral": "Neutral"}, task="sentiment")
    tiny_model(stage / "trained_models" / "event_distilroberta_ft", list(TOPICS), TOPICS)
    (stage / "metrics.json").write_text(json.dumps({"smoke": True}), encoding="utf-8")
    (stage / "predictions_test.json").write_text(json.dumps({}), encoding="utf-8")
    zpath = tmp_path / "trained_models.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        for f in stage.rglob("*"):
            if f.is_file():
                z.write(f, f.relative_to(stage))
    monkeypatch.setattr(imp, "DEST", tmp_path / "models" / "finetuned")
    monkeypatch.setattr(imp, "PUBLIC_EVAL", tmp_path / "eval_public")
    monkeypatch.setattr(imp, "EXT", tmp_path / "no_external")  # agreement check skips without the test CSVs
    monkeypatch.setattr("sys.argv", ["import_trained_models.py", str(zpath)])
    assert imp.main() == 0
    assert (tmp_path / "models/finetuned/sentiment_finbert_ft/config.json").exists()
    assert (tmp_path / "models/finetuned/event_distilroberta_ft/risk_engine_labels.json").exists()
    assert json.loads((tmp_path / "eval_public/import_check.json").read_text())["smoke_run"] is True
