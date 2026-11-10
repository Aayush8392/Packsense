import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fix_review_photo_page as p  # noqa: E402

T = {"fat": 3.0, "carbohydrates": 20.0, "proteins": 5.0}
OFF = {"fat": 30.0, "carbohydrates": 20.0, "proteins": 5.0}


def case(code, who, truth):
    return {"code": code, "who": who, "truth": truth, "basis": "per 100 g"}


def test_selection_takes_every_neither_and_mismatch_and_a_fixed_number_of_controls():
    cases = [case("n1", "neither", None), case("m1", "contributor", T), case("r1", "hybrid", T)] + [case(f"r{i}", "contributor", T) for i in range(2, 14)]
    photo = {"n1": T, "m1": OFF, **{f"r{i}": T for i in range(1, 14)}}                      # m1: the photo reading disagrees with the known-right table
    comparison = {c["code"]: {"right": c["truth"], "wrong": OFF, "hybrid": OFF} for c in cases}
    sel = p.select(cases, photo, comparison)
    kinds = [s["kind"] for s in sel]
    assert kinds.count("neither") == 1 and kinds.count("mismatch") == 1 and kinds.count("control") == p.CONTROLS
    assert [s["code"] for s in p.select(list(reversed(cases)), photo, comparison)] == [s["code"] for s in sel]      # the same cases in the same order


def test_a_case_without_a_photo_reading_is_left_out():
    assert p.select([case("n1", "neither", None)], {"n1": None}, {"n1": {"right": None, "wrong": None, "hybrid": OFF}}) == []


def test_position_tells_nothing_and_the_key_stays_out_of_the_page():
    row = {"code": "5", "serving_size": "50 g"}
    item, key = p.build(row, {"kind": "neither"}, T, OFF, {"fat": 30.0}, None, {"basis": "per 100 g"})
    assert {key["A"], key["B"]} == {"photo", "other"} and key["kind"] == "neither"
    assert not ({"kind", "source", "photo"} & set(item)) and (item["A"] if key["A"] == "photo" else item["B"]) == {"fat": 3.0, "carbohydrates": 20.0, "proteins": 5.0}      # nothing in the item names the source


def test_join_counts_the_photo_table_as_right_when_chosen_or_both():
    key = {"1": {"A": "photo", "B": "other", "kind": "neither"}, "2": {"A": "other", "B": "photo", "kind": "mismatch"}, "3": {"A": "photo", "B": "other", "kind": "control"}}
    assert p.join({"1": "A", "2": "A", "3": "both"}, key) == {"neither": {"photo_right": 1}, "mismatch": {"photo_wrong": 1}, "control": {"photo_right": 1}}
