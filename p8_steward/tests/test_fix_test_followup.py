import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fix_test_followup as f  # noqa: E402

B = {"fat": 30.0, "carbohydrates": 20.0, "sugars": 15.0}


def test_relation_categories():
    key = {"fat": 3.0, "carbohydrates": 20.0, "sugars": 15.0}
    assert f.relation(B, {"fat": 3.2, "carbohydrates": 20.0, "sugars": 15.0}, key) == "same_fields_near"        # 0.2 against an allowance of 0.3 for fat
    assert f.relation(B, {"fat": 9.0, "carbohydrates": 20.0, "sugars": 15.0}, key) == "same_fields_far"
    assert f.relation(B, {"fat": 30.0, "carbohydrates": 20.0, "sugars": 1.0}, key) == "no_shared_field"
    assert f.relation(B, {"fat": 3.1, "carbohydrates": 20.0, "sugars": 1.0}, key) == "overlapping_fields_near"


def test_field_score_is_over_the_fields_the_fix_changed():
    key = {"fat": 3.0, "carbohydrates": 20.0, "sugars": 15.0}
    assert f.field_score(B, {"fat": 3.0, "carbohydrates": 20.0, "sugars": 15.0}, key) == 1.0
    assert f.field_score(B, {"fat": 9.0, "carbohydrates": 20.0, "sugars": 15.0}, key) == 0.0
    assert f.field_score(B, B, B) is None


def test_latest_after_takes_newest_observation_after_the_fix_only():
    feats = [{"snapshot_date": "2026-05-03", "b_fat": "1.0"}, {"snapshot_date": "2026-06-07", "b_fat": "2.0"}, {"snapshot_date": "2026-05-10", "b_fat": "9.0"}]
    assert f.latest_after("2026-05-03", feats, []) == {"fat": 2.0}
    assert f.latest_after("2026-06-07", feats, []) is None
    silver = [{"nutrition_per": "100g", "last_modified_t": "1782000000", "fat": "5.0"}, {"nutrition_per": None, "last_modified_t": "1783000000", "fat": "7.0"}]
    assert f.latest_after("2026-06-07", feats, silver) == {"fat": 5.0}          # 1782000000 is 2026-06-21, after the 7 June fix; the per-serving row is ignored
