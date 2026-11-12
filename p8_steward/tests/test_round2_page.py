import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import round2_page as rp  # noqa: E402

CODES = [f"{i:013d}" for i in range(200)]


def test_the_random_70_is_the_first_70_in_hash_order_and_does_not_depend_on_input_order():
    a, b = rp.random70(CODES), rp.random70(list(reversed(CODES)))
    assert len(a) == 70 and a == b
    assert a == sorted(CODES, key=lambda c: rp.h("judge-2:", c))[:70]


def test_page_order_is_one_shuffle_and_the_swap_is_a_hash_parity():
    o = rp.page_order(CODES)
    assert sorted(o) == CODES and o != CODES and o == rp.page_order(list(reversed(CODES)))
    firsts = [rp.photo_first(c) for c in CODES]
    assert 60 < sum(firsts) < 140


def test_the_page_item_puts_the_photo_table_and_the_contributors_record_on_blind_sides(monkeypatch):
    row = {"code": CODES[3], "serving_size": "30 g", "flags": ""}
    monkeypatch.setattr(rp.t, "key", lambda r: {"fat": 1.0, "proteins": 2.0})
    monkeypatch.setattr(rp.t, "before", lambda r: {"fat": 9.0})
    item, k = rp.build_item(row, {"fat": 1.0, "proteins": 2.0, "sugars": 3.0}, None, None)
    assert item["stored_before"] == {"fat": 9.0}
    assert {k["A"], k["B"]} == {"photo", "contributor"}
    photo_side = item["A"] if k["A"] == "photo" else item["B"]
    assert photo_side == {"fat": 1.0, "proteins": 2.0, "sugars": 3.0}


def test_a_local_photo_becomes_a_data_address(tmp_path):
    f = tmp_path / "a.jpg"
    f.write_bytes(b"\xff\xd8\xffabc")
    assert rp.data_uri(f) == "data:image/jpeg;base64,/9j/YWJj"


def test_an_excluded_case_leaves_every_count_whatever_the_answer_and_is_listed_apart():
    codes = CODES[:4]
    key = {c: {"A": "photo", "B": "contributor"} for c in codes}
    dec = {c: {"table": {"fat": 1}, "types": ["rule2", "differ"]} for c in codes}
    base = {codes[0]: "A", codes[1]: "A", codes[2]: "B"}
    for given in ("A", "B", "neither", "both"):
        s = rp.score({**base, codes[3]: given}, key, dec, codes, {codes[3]: "two columns"})
        assert (s["full_set"]["judged"], s["full_set"]["photo_right"], s["random_70"]["judged"], s["shown"]) == (3, 2, 3, 3)
        assert s["by_type"]["rule2"]["judged"] == 3 and s["excluded_apart"][codes[3]]["answer_given"] == given


def test_scoring_counts_photo_right_for_the_photo_or_both_and_excludes_unsure():
    codes = CODES[:6]
    key = {c: {"A": "photo", "B": "contributor"} for c in codes}
    dec = {c: {"table": {"fat": 1}, "types": ["rule2", "match"]} for c in codes}
    answers = {codes[0]: "A", codes[1]: "both", codes[2]: "B", codes[3]: "neither", codes[4]: "unsure"}      # codes[5] not answered yet
    s = rp.score(answers, key, dec, codes)
    full = s["full_set"]
    assert (full["judged"], full["photo_right"], full["unsure"], full["contributor_right"]) == (4, 2, 1, 2)
    assert s["shown"] == 6 and s["answered"] == 5
    assert s["by_type"]["rule2"]["judged"] == 4 and s["by_type"]["rule1"]["judged"] == 0
    assert full["wilson_lower_unsure_counted_wrong"] < full["wilson_95"][0]
