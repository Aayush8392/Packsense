"""Tests for the stage-1 comparison (nightly/compare_stage1.py) on small synthetic data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import compare_stage1 as cs  # noqa: E402

TABLE = {"energy_kcal": 90.0, "energy_kj": 376.0, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}
N = "2026-11-13"


def done(outcome, reason=None, night=N):
    return {"record_hash": "h", "outcome": outcome, "reason": reason, "night": night}


def line(code, **over):
    return {"code": code, "values": {**TABLE, **over}}


def shown(code):
    return {"code": code, "rule2": True, "table": dict(TABLE)}


def silent(code):
    return {"code": code, "rule2": False, "table": None}


def test_each_kind_of_agreement_and_difference_is_counted_by_barcode():
    queue = {"done": {"1": done("line"), "2": done("line"), "3": done("silence", "no_agreement"), "4": done("silence", "no_photo"), "5": done("line"), "6": done("line", night="old")}}
    decisions = {"1": shown("1"), "2": shown("2"), "3": silent("3"), "4": shown("4"), "5": silent("5"), "6": shown("6"), "7": shown("7")}
    lines = [line("1"), line("2", fat=5.0, carbohydrates=89.0, proteins=1.0), line("5")]
    r = cs.compare(queue, lines, {"stopped": None, "calls": 40}, decisions, N)
    assert r["finished"] == 5 and r["both_shown"] == 2 and r["tables_agree"] == 1 and r["tables_differ"] == ["2"] and r["both_silent"] == 1
    assert r["only_saved_shows"] == [{"code": "4", "night": "no_photo"}] and r["only_night_shows"] == ["5"] and r["night_silences"] == {"no_agreement": 1, "no_photo": 1}
    assert r["same_show_or_silence"] == 3 and r["share_same"] == 0.6 and r["calls"] == 40


def test_values_the_night_added_are_not_a_difference_and_exactness_is_on_shared_fields_only():
    queue = {"done": {"1": done("line"), "2": done("line")}}
    decisions = {"1": shown("1"), "2": shown("2")}
    lines = [line("1", fiber=3.0), line("2", fat=0.51)]                       # 1: an extra field (guard v2); 2: a value within the 10% rule but not exact
    r = cs.compare(queue, lines, {}, decisions, N)
    assert r["tables_agree"] == 2 and r["tables_differ"] == [] and r["exact_on_shared"] == 1


def test_a_product_without_a_saved_decision_is_counted_apart_and_an_empty_night_has_no_share():
    r = cs.compare({"done": {"9": done("line")}}, [line("9")], {}, {}, N)
    assert r["finished"] == 1 and r["no_saved_decision"] == 1 and r["share_same"] is None
