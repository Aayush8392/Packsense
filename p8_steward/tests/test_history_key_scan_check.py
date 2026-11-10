import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history_key_scan_check as s  # noqa: E402


def scan(*words):
    return {"responses": [{"fullTextAnnotation": {"pages": [{"blocks": [{"paragraphs": [{"words": [
        {"boundingBox": {"vertices": [{"x": i * 10, "y": 0}, {"x": i * 10 + 8, "y": 0}, {"x": i * 10 + 8, "y": 5}, {"x": i * 10, "y": 5}]}, "symbols": [{"text": w}]}
        for i, w in enumerate(words)]}]}]}]}}]}


ROW = {"code": "1", "a_fat": 40.0, "b_fat": 3.5, "a_proteins": 5.0, "b_proteins": 5.0, "a_salt": None, "b_salt": None}


def test_pick_is_fixed_one_per_code_and_stable_under_reordering():
    c = [{"code": str(i)} for i in range(20)] + [{"code": "3"}]
    a, b = s.pick(c, 5), s.pick(list(reversed(c)), 5)
    assert [r["code"] for r in a] == [r["code"] for r in b] and len({r["code"] for r in a}) == 5


def test_changed_fields_ignores_unchanged_and_missing():
    assert s.changed_fields(ROW) == ["fat"]
    assert s.changed_fields({**ROW, "b_fat": None}) == ["fat"]


def test_supported_when_new_value_is_printed_and_old_is_not():
    r = s.judge(ROW, scan("Fat", "3,5", "g"))
    assert r["after_all_printed"] and not r["before_all_printed"]


def test_not_supported_when_new_value_is_not_in_the_text_and_no_scan_is_flagged():
    assert not s.judge(ROW, scan("Fat", "40", "g"))["after_all_printed"]
    assert s.judge(ROW, {})["status"] == "no_scan"


def test_summary_counts_only_scored_rows():
    rs = [{"status": "scanned", "removed_only": False, "after_all_printed": True, "before_all_printed": False},
          {"status": "scanned", "removed_only": False, "after_all_printed": False, "before_all_printed": False}, {"status": "no_scan"}]
    out = s.summarise(rs)
    assert out["scored"] == 2 and out["supported_after_all_printed"] == 1 and out["supported_and_old_not_printed"] == 1 and out["no_scan"] == 1
