"""The evaluation helpers on plain hand-made numbers (the arithmetic needs no product data) and on real flag families from the label fixture."""
import json
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import triage_eval as te  # noqa: E402

SLICE = json.loads((HERE / "fixtures" / "triage_slice.json").read_text(encoding="utf-8"))


def test_the_wilson_interval_matches_known_values_and_the_edges():
    lo, hi = te.wilson(8, 10)
    assert (round(lo, 3), round(hi, 3)) == (0.490, 0.943)                  # the textbook example
    lo, hi = te.wilson(0, 30)
    assert lo == 0.0 and round(hi, 3) == 0.114
    lo, hi = te.wilson(30, 30)
    assert hi == 1.0 and round(lo, 3) == 0.886
    assert te.wilson(0, 0) == (0.0, 1.0)
    assert te.wilson(73, 100)[0] < 0.73 < te.wilson(73, 100)[1]


def test_ranking_does_not_depend_on_row_order_and_ties_are_hash_ordered():
    ids = [f"id{i}" for i in range(50)]
    scores = {i: float(n % 3) for n, i in enumerate(ids)}
    first = te.rank(scores)
    shuffled = dict(random.Random(1).sample(list(scores.items()), len(scores)))
    assert te.rank(shuffled) == first
    assert [scores[i] for i in first] == sorted(scores.values(), reverse=True)
    top_group = [i for i in first if scores[i] == 2.0]
    assert top_group == sorted(top_group, key=te.tie_key)


def _rows(labels, severity="error", family="x"):
    return [{"id": f"r{i}", "severity": severity, "family": family, "label": lab, "week": 0} for i, lab in enumerate(labels)]


def test_precision_at_k_counts_hits_in_the_top_k_only():
    rows = _rows([1, 1, 0, 1, 0, 0, 0, 0, 0, 0])
    scores = {f"r{i}": 10 - i for i in range(10)}                          # the file order IS the score order
    res = te.precision_at_k(rows, scores, 4)
    assert (res["k"], res["hits"], res["precision"], res["base_rate"]) == (4, 3, 0.75, 0.3)
    assert te.precision_at_k(rows, scores, 100)["k"] == 10                 # fewer rows than k
    assert te.precision_at_k([], {}, 5)["precision"] == 0.0


def test_severity_and_rule_baselines_order_real_flag_families():
    fams = {(r[2], r[4]) for r in SLICE["open_flags"]["rows"]}
    covered = next(f for s, f in fams if s == "error" and te.rules_lib.rule_for_family(f))
    not_covered = next(f for s, f in fams if s == "error" and te.rules_lib.rule_for_family(f) is None)
    warn = next(f for s, f in fams if s == "warning")
    rows = [{"id": "a", "severity": "error", "family": covered}, {"id": "b", "severity": "error", "family": not_covered},
            {"id": "c", "severity": "warning", "family": warn}]
    assert te.severity_scores(rows) == {"a": 2.0, "b": 2.0, "c": 1.0}
    assert te.rule_scores(rows)["a"] > te.rule_scores(rows)["b"] > te.rule_scores(rows)["c"]
    assert [r["id"] for r in te.uncovered(rows)] == ["b", "c"]
    assert set(te.random_scores(rows).values()) == {0.0}


def test_the_time_split_purges_training_weeks_whose_label_reaches_into_the_test():
    s = te.split_weeks(list(range(10)), steps=4, n_test=3)
    assert s["test"] == [7, 8, 9] and s["train"] == [0, 1, 2, 3] and s["purged"] == [4, 5, 6]
    assert all(t + 4 <= 7 for t in s["train"])
    s2 = te.split_weeks([0, 1, 2, 3, 4, 5], steps=1, n_test=2)
    assert s2 == {"train": [0, 1, 2, 3], "purged": [], "test": [4, 5]}
    with pytest.raises(ValueError):
        te.split_weeks([0, 1], steps=1, n_test=2)
    with pytest.raises(ValueError):
        te.split_weeks([0, 1, 2], steps=1, n_test=0)


def test_the_kill_rule_needs_both_a_better_point_and_a_lower_bound_above_the_baseline():
    def res(hits, k):
        lo, hi = te.wilson(hits, k)
        return {"k": k, "hits": hits, "precision": hits / k, "low": lo, "high": hi}
    base = {"random": res(5, 1000), "severity": res(20, 1000), "rules": res(30, 1000)}
    out = te.kill_rule(res(80, 1000), base)
    assert out["passed"] and out["best_baseline"] == "rules" and out["model_low"] > 0.03
    assert not te.kill_rule(res(35, 1000), base)["passed"]                  # better point, but the interval still contains the baseline
    assert not te.kill_rule(res(25, 1000), base)["passed"]                  # worse than the best baseline
    assert te.HEADLINE_K == 1000
