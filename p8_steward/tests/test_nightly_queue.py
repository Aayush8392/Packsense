"""Tests for the nightly retry queue (nightly/queue_lib.py)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import queue_lib as q  # noqa: E402


def cand(code, h="h1", new=False):
    return {"code": code, "record_hash": h, "new": new}


def state_with(*cands, today="2026-11-13"):
    s = q.new_state()
    q.merge_candidates(s, list(cands), today)
    return s


def test_order_is_new_then_missed_then_backlog():
    s = state_with(cand("1"), cand("2", new=True), cand("3"))
    q.settle(s, "3", "error", "2026-11-12", "unavailable")          # a missed product
    assert q.take(s, "2026-11-13", 10) == ["2", "3", "1"]


def test_inside_a_tier_the_order_is_a_fixed_hash_order_not_the_input_order():
    s1 = state_with(cand("111"), cand("222"), cand("333"))
    s2 = state_with(cand("333"), cand("111"), cand("222"))
    assert q.take(s1, "d", 10) == q.take(s2, "d", 10) == sorted(["111", "222", "333"], key=q.order_key)


def test_a_product_already_tried_tonight_is_not_taken_again():
    s = state_with(cand("1"))
    q.settle(s, "1", "error", "2026-11-13", "unavailable")
    assert q.take(s, "2026-11-13", 10) == [] and q.take(s, "2026-11-14", 10) == ["1"]


def test_a_transient_error_costs_an_attempt_and_the_third_one_gives_up():
    s = state_with(cand("1"))
    for night in ("n1", "n2"):
        q.settle(s, "1", "error", night, "unavailable")
        assert "1" in s["items"]
    q.settle(s, "1", "error", "n3", "unavailable")
    assert "1" not in s["items"] and s["done"]["1"]["outcome"] == "gave_up" and q.MAX_ATTEMPTS == 3


def test_a_line_or_a_content_silence_is_final_until_the_record_changes():
    s = state_with(cand("1"), cand("2"))
    q.settle(s, "1", "line", "n1")
    q.settle(s, "2", "silence", "n1", "no_agreement")
    assert q.merge_candidates(s, [cand("1"), cand("2")], "n2") == {"added": 0, "requeued": 0, "removed": 0}
    assert s["items"] == {} and q.counts(s)["line"] == 1 and q.counts(s)["silence"] == 1
    r = q.merge_candidates(s, [cand("1", h="h2"), cand("2")], "n3")
    assert r["requeued"] == 1 and s["items"]["1"]["new"] is True and "1" not in s["done"] and "2" in s["done"]


def test_a_changed_record_resets_the_attempts_of_a_queued_product():
    s = state_with(cand("1"))
    q.settle(s, "1", "error", "n1", "unavailable")
    q.merge_candidates(s, [cand("1", h="h2")], "n2")
    assert s["items"]["1"]["attempts"] == 0 and s["items"]["1"]["record_hash"] == "h2"


def test_a_product_whose_flag_closed_leaves_the_state_everywhere():
    s = state_with(cand("1"), cand("2"))
    q.settle(s, "1", "line", "n1")
    assert q.merge_candidates(s, [], "n2")["removed"] == 2
    assert s == q.new_state()


def test_take_respects_the_limit_and_counts_report_the_tiers():
    s = state_with(cand("1"), cand("2", new=True), cand("3"))
    assert len(q.take(s, "d", 2)) == 2
    c = q.counts(s)
    assert (c["queued"], c["queued_new"], c["queued_backlog"], c["queued_missed"]) == (3, 1, 2, 0)


def test_an_unknown_outcome_is_refused():
    s = state_with(cand("1"))
    with pytest.raises(ValueError):
        q.settle(s, "1", "perhaps", "n1")
