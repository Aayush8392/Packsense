"""Tests for the stage-input builder (nightly/make_stage_inputs.py) on a small synthetic fixture (the real files are gitignored)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import make_stage_inputs as ms  # noqa: E402

TABLE = {"energy_kcal": 90.0, "energy_kj": 376.0, "fat": 0.5, "saturated_fat": 0.3, "carbohydrates": 8.9, "sugars": 6.5, "proteins": 12.4, "salt": 0.06}


def row(code):
    return {"code": code, "a_fat": "0.5", "a_energy_kcal": "90.0", "a_salt": "0.06", "b_fat": "9.9"}


def fixture(n=30):
    codes = [f"{10000000 + i}" for i in range(n)]
    rows = [row(c) for c in codes]
    decisions = {c: {"code": c, "rule2": True, "table": dict(TABLE, fat=0.5 + i / 100)} for i, c in enumerate(codes)}
    key = {c: ("decoy" if i % 5 == 0 else "sample") for i, c in enumerate(codes)}
    answers = {c: ("wrong" if key[c] == "decoy" else "right") for c in codes}
    return rows, decisions, key, answers


def test_the_canary_is_ten_judged_right_sampled_lines_with_their_shown_tables():
    rows, decisions, key, answers = fixture()
    cands, canary = ms.build(rows, decisions, key, answers, today="2026-11-13")
    codes = [c["code"] for c in canary["canary"]]
    assert len(codes) == 10 and all(key[c] == "sample" and answers[c] == "right" for c in codes)
    first = canary["canary"][0]
    assert first["expected"] == {k: v for k, v in decisions[first["code"]]["table"].items()} and first["stored"] == {"fat": 0.5, "energy_kcal": 90.0, "salt": 0.06}


def test_a_line_that_was_silent_or_judged_wrong_or_is_a_decoy_is_never_a_canary():
    rows, decisions, key, answers = fixture(14)
    for c in list(decisions)[1:6]:
        decisions[c] = {"code": c, "rule2": False, "table": None}                    # silent
    answers[list(decisions)[7]] = "unsure"
    _, canary = ms.build(rows, decisions, key, answers, n_canary=4)
    for c in canary["canary"]:
        assert decisions[c["code"]]["rule2"] and key[c["code"]] == "sample" and answers[c["code"]] == "right"


def test_candidates_exclude_the_canary_mark_exactly_n_new_and_use_the_pre_fix_side():
    rows, decisions, key, answers = fixture()
    cands, canary = ms.build(rows, decisions, key, answers, n_new=7, today="2026-11-13")
    c_codes = {c["code"] for c in cands["candidates"]}
    assert cands["exported"] == "2026-11-13" and len(c_codes) == 20 and not c_codes & {c["code"] for c in canary["canary"]}
    assert sum(c["new"] for c in cands["candidates"]) == 7 and all(c["stored"]["fat"] == 0.5 for c in cands["candidates"])      # the a_ side, never b_


def test_the_build_is_deterministic_and_does_not_depend_on_input_order():
    rows, decisions, key, answers = fixture()
    a = ms.build(rows, decisions, key, answers, today="d")
    b = ms.build(list(reversed(rows)), decisions, key, answers, today="d")
    assert a == b


def test_too_few_judged_right_lines_is_an_error_not_a_smaller_canary():
    rows, decisions, key, answers = fixture(8)
    with pytest.raises(ValueError):
        ms.build(rows, decisions, key, answers, n_canary=10)
