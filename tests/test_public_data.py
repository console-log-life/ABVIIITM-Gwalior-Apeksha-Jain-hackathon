"""Public-dataset splits: leakage removal, deterministic stratified dev split, checksums, label maps (no downloads)."""

from __future__ import annotations

import json
from collections import Counter

import pytest
import yaml

from app.config import PROJECT_ROOT
from risk_engine.schemas import EVENT_TYPES
from risk_engine.training.public_data import (
    DATASETS,
    build_split,
    checksum,
    leakage_ids,
    map_labels,
    normalize,
    stratified_dev,
)

SPLITS = PROJECT_ROOT / "data" / "splits"


def test_normalize_drops_links_and_case():
    assert normalize("Fed HIKES  rates https://t.co/abc") == normalize("fed hikes rates http://t.co/xyz")


def test_leakage_exact_after_link_removal_and_near_duplicates():
    train = ["Fed hikes rates https://t.co/1", "Apple buys a startup for $1bn", "Totally unrelated tweet here",
             "Tesla deliveries beat expectations this quarter!"]
    test = ["fed hikes rates https://t.co/2", "Tesla deliveries beat expectations this quarter"]
    assert leakage_ids(train, test) == [0, 3]


def test_stratified_dev_is_deterministic_and_stratified():
    labels = [0] * 50 + [1] * 30 + [2] * 20
    ids = list(range(100))
    dev = stratified_dev(ids, labels, 0.1, 42)
    assert dev == stratified_dev(ids, labels, 0.1, 42)
    assert Counter(labels[i] for i in dev) == {0: 5, 1: 3, 2: 2}
    assert dev != stratified_dev(ids, labels, 0.1, 7)


def test_build_split_partitions_and_checksum():
    train = [f"headline number {i} about markets" if i % 7 else f"duplicate story {i}" for i in range(60)]
    labels = [i % 3 for i in range(60)]
    test = ["duplicate story 7", "something new"]
    sp = build_split(train, labels, test)
    tr, dv, rm = set(sp["train_ids"]), set(sp["dev_ids"]), set(sp["removed_leak_ids"])
    assert 7 in rm and not (tr & dv) and not (tr & rm) and not (dv & rm)
    assert tr | dv | rm == set(range(60)) and sp["test_ids"] == [0, 1]
    assert sp["sha256"] == checksum(sp)


def test_topic_map_covers_all_20_topics_with_valid_classes():
    taxonomy = PROJECT_ROOT / "src/risk_engine/event_classifier/taxonomy.yaml"
    tmap = yaml.safe_load(taxonomy.read_text("utf-8"))["topic_map"]
    assert set(tmap) == set(DATASETS["topic"]["labels"]) and set(tmap.values()) <= set(EVENT_TYPES)
    assert tmap["IPO"] == "Other" and tmap["Legal | Regulation"] == "Regulatory"
    assert map_labels(["Bearish", "Bullish"], DATASETS["sentiment"]["to_ours"]) == ["Negative", "Positive"]
    with pytest.raises(ValueError):
        map_labels(["Unknown"], tmap)


@pytest.mark.parametrize("key", ["sentiment", "topic"])
def test_committed_split_files_are_consistent(key):
    path = SPLITS / f"{key}.json"
    if not path.exists():
        pytest.skip("run src/scripts/datasets/prepare_public.py")
    sp = json.loads(path.read_text("utf-8"))
    assert sp["sha256"] == checksum(sp) and sp["seed"] == 42 and sp["dataset"] == DATASETS[key]["hf_id"]
    tr, dv, rm = set(sp["train_ids"]), set(sp["dev_ids"]), set(sp["removed_leak_ids"])
    assert not (tr & dv) and not (tr & rm) and not (dv & rm)
    assert len(tr | dv | rm) == sp["hf_train_rows"] and len(sp["test_ids"]) == sp["hf_validation_rows"]
