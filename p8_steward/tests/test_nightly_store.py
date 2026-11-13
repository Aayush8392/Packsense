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


# ---------------------------------------------------------------- hardening (2026-11-13)
def cands_doc(rows, exported="2026-11-13"):
    return {"exported": exported, "candidates": rows}


def good(code="10000001", **stored):
    return {"code": code, "stored": {"fat": 0.5, "salt": 0.06, **stored}, "new": False}


def test_an_invalid_candidate_is_dropped_and_counted_and_unknown_fields_are_left_out():
    b = Backend()
    rows = [good(f"1000000{i}") for i in range(30)]
    rows.append({"code": "30000099", "stored": {"fat": "abc"}, "new": False})                          # one in 31: under the 5% limit
    rows[0]["stored"]["colour"] = "red"
    put(b, st.CANDIDATES, cands_doc(rows))
    s = st.Store(b)
    got = s.load_candidates()
    assert len(got) == 30 and s.invalid == 1 and got[0]["stored"] == {"fat": 0.5, "salt": 0.06} and "30000099" not in {c["code"] for c in got}


def test_each_kind_of_invalid_candidate_is_recognised():
    for bad in ({"code": "12", "stored": {"fat": 1}}, {"code": "10000001", "stored": {"fat": -1}}, {"code": "10000001", "stored": {"fat": float("nan")}},
                {"code": "10000001", "stored": {"fat": True}}, {"code": "10000001", "stored": {"fat": 1e9}}, {"code": "10000001", "stored": "x"}, {"code": 10000001, "stored": {}}, "x"):
        b = Backend()
        put(b, st.CANDIDATES, cands_doc([good(f"2000000{i}") for i in range(30)] + [bad]))
        s = st.Store(b)
        s.load_candidates()
        assert s.invalid == 1, bad


def test_a_broken_export_is_an_error_not_a_smaller_night():
    b = Backend()
    put(b, st.CANDIDATES, cands_doc([good(f"1000000{i}") for i in range(8)] + [{"code": "x", "stored": {}}] * 2))        # 2 of 10 invalid
    with pytest.raises(st.StoreError):
        st.Store(b).load_candidates()
    put(b, st.CANDIDATES, cands_doc([{"code": "x", "stored": {}}]))
    with pytest.raises(st.StoreError):
        st.Store(b).load_candidates()


def test_a_stale_or_undated_export_is_refused_only_when_a_limit_is_asked_for():
    b = Backend()
    s = st.Store(b)
    put(b, st.CANDIDATES, cands_doc([good()], exported="2026-11-10"))
    assert len(s.load_candidates()) == 1                                                                # no limit asked (scratch, fetch-only)
    assert len(s.load_candidates("2026-11-12", 2)) == 1                                                  # 2 days: allowed
    with pytest.raises(st.StoreError, match="3 days old"):
        s.load_candidates("2026-11-13", 2)
    put(b, st.CANDIDATES, {"candidates": [good()]})
    with pytest.raises(st.StoreError, match="no usable export date"):
        s.load_candidates("2026-11-13", 2)
    put(b, st.CANDIDATES, cands_doc([good()], exported="2026-12-01"))
    with pytest.raises(st.StoreError):
        s.load_candidates("2026-11-13", 2)                                                              # an export from the future is wrong too


class FakeApi:
    def __init__(self, fail_times):
        self.fail_times, self.calls = fail_times, 0

    def create_commit(self, **kw):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ConnectionError("hub down")
        self.kw = kw


def test_the_real_backend_retries_a_failed_commit_and_gives_up_with_a_clear_error():
    waits = []
    ok = FakeApi(2)
    st.HfBackend("o/r", "t", api=ok, sleep=waits.append, make_op=lambda p, b: (p, b)).commit({"a.json": b"{}"}, "m")
    assert ok.calls == 3 and waits == [5, 20] and ok.kw["repo_type"] == "dataset" and ok.kw["commit_message"] == "m" and ok.kw["operations"] == [("a.json", b"{}")]
    waits.clear()
    dead = FakeApi(99)
    with pytest.raises(st.StoreError, match=r"failed after 3 tries \(ConnectionError\)") as e:
        st.HfBackend("o/r", "t", api=dead, sleep=waits.append, make_op=lambda p, b: (p, b)).commit({"a.json": b"{}"}, "m")
    assert dead.calls == 3 and waits == [5, 20] and "hub down" not in str(e.value)
