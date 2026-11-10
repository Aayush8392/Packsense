import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history_key_check as h  # noqa: E402

ERR = ["en:nutrition-packaging-as-sold-100g-value-over-105-sodium"]


def v(t, errors, per="100g", **vals):
    return {"last_modified_t": t, "last_modified_ts": str(t), "rev": t, "nutrition_per": per, "data_quality_errors_tags": errors, **vals}


CARD = {"code": "1", "group": "D_sums_too_large", "per100": {"fat": 3.0, "carbohydrates": 20.0}}


def test_agree_when_flag_removed_and_new_values_match_key():
    r = h.judge(CARD, [v(1, ERR, fat=30.0, carbohydrates=20.0), v(2, [], fat=3.0, carbohydrates=20.0)])
    assert r["status"] == "fix_found" and r["agrees"] and not r["agreed_before"]


def test_disagree_when_fix_clears_flag_with_other_values():
    r = h.judge(CARD, [v(1, ERR, fat=30.0, carbohydrates=20.0), v(2, [], fat=9.0, carbohydrates=20.0)])
    assert r["status"] == "fix_found" and not r["agrees"] and r["wrong_after"] == ["fat"]


def test_no_fix_when_flag_stays_or_values_unchanged_or_deleted_or_per_serving():
    assert h.judge(CARD, [v(1, ERR, fat=30.0), v(2, ERR, fat=3.0)])["status"] == "no_fix_found"
    assert h.judge(CARD, [v(1, ERR, fat=30.0), v(2, [], fat=30.0)])["status"] == "no_fix_found"
    assert h.judge(CARD, [v(1, ERR, fat=30.0), v(2, [])])["status"] == "no_fix_found"
    assert h.judge(CARD, [v(1, ERR, fat=30.0), v(2, [], per=None, fat=3.0)])["status"] == "no_fix_found"
    assert h.judge(CARD, [v(1, ERR, fat=30.0)])["status"] == "no_fix_found"


def test_float_noise_is_not_a_change_and_order_is_by_time():
    assert not h.changed({"fat": 3.4666666666666}, {"fat": 3.46666666666667})
    r = h.judge(CARD, [v(2, [], fat=3.0, carbohydrates=20.0), v(1, ERR, fat=30.0, carbohydrates=20.0)])
    assert r["agrees"]


def test_summary_counts():
    rs = [{"status": "fix_found", "compared": 2, "agrees": True, "agreed_before": False}, {"status": "no_fix_found"},
          {"status": "fix_found", "compared": 2, "agrees": False, "agreed_before": False}]
    assert h.summarise(rs) == {"keyed": 3, "fix_found": 2, "agree": 1, "agreed_before_the_fix": 0}
