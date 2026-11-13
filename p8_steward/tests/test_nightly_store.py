"""Tests for the results-dataset store (nightly/store.py) with a dict backend: input checks, one commit per night, current-lines upkeep, reruns."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import queue_lib as ql  # noqa: E402
from nightly import store as st  # noqa: E402

STORED = {"energy_kcal": 90.0, "fat": 0.5, "salt": 0.06}


class Backend:
    def __init__(self, files=None):
        self.files = dict(files or {})
        self.commits = []

    def read(self, path):
        return self.files.get(path)

    def commit(self, files, message):
        self.commits.append((dict(files), message))
        self.files.update(files)


def put(b, path, obj):
    b.files[path] = json.dumps(obj).encode("utf-8")


def line(code, fat=0.5):
    return {"code": code, "values": {"fat": fat}}


def state_with_lines(*codes):
    s = ql.new_state()
    for c in codes:
        s["done"][c] = {"record_hash": "h", "outcome": "line", "reason": None, "night": "n"}
    return s


def test_a_missing_state_is_a_first_night_but_a_missing_input_is_an_error():
    s = st.Store(Backend())
    assert s.load_state() == ql.new_state()
    for fn in (s.load_candidates, s.load_canary):
        with pytest.raises(st.StoreError):
            fn()


def test_inputs_are_checked_for_shape_and_never_accepted_empty():
    b = Backend()
    s = st.Store(b)
    put(b, st.CANDIDATES, {"exported": "d", "candidates": []})
    with pytest.raises(st.StoreError):
        s.load_candidates()
    put(b, st.CANDIDATES, {"candidates": [{"code": "1"}]})
    with pytest.raises(st.StoreError):
        s.load_candidates()
    put(b, st.CANDIDATES, {"candidates": [{"code": "10000001", "stored": STORED, "new": True}]})
    assert s.load_candidates()[0]["code"] == "10000001"
    put(b, st.CANARY, {"canary": [{"code": "2", "stored": STORED}]})
    with pytest.raises(st.StoreError):
        s.load_canary()
    b.files[st.QUEUE] = b"not json"
    with pytest.raises(st.StoreError):
        s.load_state()
    put(b, st.QUEUE, {"version": 2, "items": {}, "done": {}})
    with pytest.raises(st.StoreError):
        s.load_state()


def test_a_night_is_one_commit_with_all_four_files_and_the_run_record_holds_no_lines():
    b = Backend()
    s = st.Store(b)
    state = state_with_lines("10000001")
    s.save_night("2026-11-13", state, {"stopped": None, "calls": 8, "lines": [line("10000001")], "silences": {"no_photo": 1}})
    assert len(b.commits) == 1
    files, message = b.commits[0]
    assert sorted(files) == ["lines/2026-11-13.json", "lines/current.json", "queue.json", "runs/2026-11-13.json"] and "1 lines" in message
    run = json.loads(files["runs/2026-11-13.json"])
    assert "lines" not in run and run["lines_added"] == 1 and run["silences"] == {"no_photo": 1}
    assert json.loads(files["queue.json"])["done"]["10000001"]["outcome"] == "line"


def test_current_lines_keep_valid_ones_replace_updated_ones_and_drop_the_rest():
    b = Backend()
    put(b, st.CURRENT, {"10000001": line("10000001"), "10000002": line("10000002"), "10000003": line("10000003")})
    s = st.Store(b)
    state = state_with_lines("10000001", "10000003")                                 # 10000002 left the state (its flag closed)
    s.save_night("n2", state, {"lines": [line("10000003", fat=9.9)]})
    cur = json.loads(b.files[st.CURRENT])
    assert sorted(cur) == ["10000001", "10000003"] and cur["10000003"]["values"]["fat"] == 9.9


def test_a_second_run_of_the_same_night_adds_to_its_lines_file():
    b = Backend()
    s = st.Store(b)
    state = state_with_lines("10000001", "10000002")
    s.save_night("n1", state, {"lines": [line("10000001")]})
    s.save_night("n1", state, {"lines": [line("10000002")]})
    assert [x["code"] for x in json.loads(b.files["lines/n1.json"])] == ["10000001", "10000002"]


def test_a_night_that_stopped_early_still_writes_its_run_record():
    b = Backend()
    st.Store(b).save_night("n1", ql.new_state(), {"stopped": "canary_failed", "lines": []})
    assert json.loads(b.files["runs/n1.json"])["stopped"] == "canary_failed" and json.loads(b.files[st.CURRENT]) == {}
