"""Tests of the identity pair model on the owner's real labelled pairs (roadmap item 19). The labelled file stays on D: (sealed, never committed), so these tests are skipped where it is absent, for instance in CI."""
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "identity"))
import eval_baselines as eb  # noqa: E402
import eval_pair_model as ev  # noqa: E402
import pair_model as pm  # noqa: E402

EVAL_INPUT = Path(os.environ.get("PACKSENSE_EVAL_INPUT", r"D:\off-catalogue-platform\label_studio\packsense_identity\eval_input.SEALED.json"))
needs_labels = pytest.mark.skipif(not EVAL_INPUT.exists(), reason="the sealed labelled pairs are not on this machine")


@pytest.fixture(scope="module")
def data():
    return json.loads(EVAL_INPUT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rows(data):
    out = [r for r in data["rows"] if r["label"] != "Cannot tell"]
    for r in out:
        r["pos"] = r["label"] in pm.POSITIVE
    return out


def test_word_overlap_bounds_and_empty():
    assert pm.word_overlap("", "") == 0.0
    assert pm.word_overlap("Parle G biscuit", "Parle G biscuit") == 1.0
    assert pm.word_overlap("Parle G biscuit", "Britannia Good Day") == 0.0
    assert 0.0 < pm.word_overlap("Parle G biscuit", "Parle G glucose biscuit 800 g") < 1.0


def test_features_missing_gap_is_flagged():
    base = {"name_score": 0.5, "size": "unknown", "text_a": "a b", "text_b": "a c"}
    assert pm.features({**base, "gap": None})[3:5] == [0.0, 1.0]
    assert pm.features({**base, "gap": 0.2})[3:5] == [0.2, 0.0]


@needs_labels
def test_every_pair_has_a_batch_and_the_weights_rebuild_the_strata(data):
    rows = data["rows"]
    assert {r["batch"] for r in rows} == {"R1", "A", "B", "C"}
    for i, size in enumerate(data["strata_sizes"]):
        assert sum(r["weight"] for r in rows if r["stratum"] == i) == pytest.approx(size)


@needs_labels
def test_features_are_complete_on_real_pairs(rows):
    for r in rows:
        f = pm.features(r)
        assert len(f) == len(pm.FEATURES)
        assert 0.0 <= f[-1] <= 1.0
        assert r["size"] in {"same", "different", "unknown"}


@needs_labels
def test_held_out_batch_is_never_in_its_own_training_set(rows):
    for res in ev.evaluate([dict(r) for r in rows]):
        assert {r["batch"] for r in res["test"]} == {res["held"]}
        assert all("model" in r for r in res["test"])


@needs_labels
def test_fit_is_deterministic_and_ranks_the_training_pairs_above_chance(rows):
    m1, m2 = pm.fit(rows), pm.fit(rows)
    assert m1 == m2
    for r in rows:
        r["model"] = pm.predict(m1, r)
    assert 0.0 < min(r["model"] for r in rows) and max(r["model"] for r in rows) < 1.0
    positives = sum(r["weight"] for r in rows if r["pos"]) / sum(r["weight"] for r in rows)
    assert eb.weighted_ap(rows, "model") > positives   # a random order would give about the share of matches
