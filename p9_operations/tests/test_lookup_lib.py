"""p9_operations/lookup_lib.py (the daily Databricks lookup) on OFF's real answers (fixtures/off_api_responses.json) with the network and the clock faked."""
import datetime as dt
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import existence_lib as rl  # noqa: E402
import lookup_lib as lib  # noqa: E402

API = json.loads((HERE / "fixtures" / "off_api_responses.json").read_text(encoding="utf-8"))["responses"]
REAL = [(r["http"], {"status": r["status"], "status_verbose": r["status_verbose"]}, None, None) for r in API]
NOW = dt.datetime(2026, 10, 21, 10, 0, 5, tzinfo=dt.timezone.utc)
RATE_LIMITED = (429, None, None, None)


def fixed_now():
    return NOW


def code_of(url):
    return url.split("/product/")[1].split(".json")[0]


class Network:
    """A fake `get`: real answers cycled over the codes (by the number in the code), with optional scripted failures per code."""

    def __init__(self, scripted=None):
        self.scripted, self.calls = {k: list(v) for k, v in (scripted or {}).items()}, []

    def __call__(self, url):
        code = code_of(url)
        self.calls.append(code)
        if self.scripted.get(code):
            return self.scripted[code].pop(0)
        return REAL[int(code) % len(REAL)]


class Clock:
    """A fake clock: sleeping advances it, and every request costs 0.3 s (the latency measured from Databricks)."""

    def __init__(self):
        self.t, self.slept = 0.0, []

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def monotonic(self):
        return self.t


def codes(n):
    return [f"{i:013d}" for i in range(n)]


def collector():
    batches = []
    return batches, batches.append


# --- choosing what to ask ------------------------------------------------------------------------------------------------------------------------

def test_the_pending_codes_are_the_first_unanswered_ones_in_list_order_up_to_the_cap():
    lst = codes(20)
    assert lib.select_pending(lst, set(), 5) == lst[:5]
    assert lib.select_pending(lst, set(lst[:3]) | {lst[5]}, 5) == lst[3:5] + lst[6:9]
    assert lib.select_pending(lst, set(lst), 5) == []
    assert lib.select_pending(lst, set(), 500) == lst


def test_the_real_candidate_codes_keep_their_order_and_none_is_asked_twice():
    real_codes = [r["code"] for r in API]
    got = lib.select_pending(real_codes + real_codes[:3], {real_codes[0]}, 100)
    assert got[0] == real_codes[1] and got.count(real_codes[1]) == 1 and real_codes[0] not in got


# --- the rows of the table ------------------------------------------------------------------------------------------------------------------------

def test_result_lines_become_rows_of_the_existence_table_with_the_run_id():
    r = API[0]
    outcome = rl.classify_response(r["http"], {"status": r["status"], "status_verbose": r["status_verbose"]})
    line = rl.result_line(r["code"], outcome, r["http"], NOW)
    (row,) = lib.table_rows([line], "run-77")
    assert row == (r["code"], dt.datetime(2026, 10, 21, 10, 0, 5), outcome["status"], outcome["detail"], "off_api_v2", None, "run-77")
    assert len(row) == len(rl.ddl_columns(rl.ddl()))


# --- the loop ---------------------------------------------------------------------------------------------------------------------------------------

def test_the_loop_writes_in_batches_pauses_between_codes_and_counts_the_answers():
    batches, write = collector()
    clock = Clock()
    out = lib.run_lookups(codes(120), write, get=Network(), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert [len(b) for b in batches] == [50, 50, 20] and out["written"] == 120 and out["asked"] == 120 and out["batches"] == 3
    assert out["answered_clearly"] == 120 and out["unconfirmed"] == 0 and out["retries"] == 0 and out["stopped"] is None
    assert clock.slept == [rl.API_PAUSE_SECONDS] * 120
    assert [x["code"] for b in batches for x in b] == codes(120)


def test_a_code_rate_limited_once_is_retried_and_the_retry_is_counted():
    batches, write = collector()
    clock = Clock()
    net = Network({codes(3)[1]: [RATE_LIMITED]})
    out = lib.run_lookups(codes(3), write, get=net, sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert out["retries"] == 1 and out["written"] == 3 and out["answered_clearly"] == 3 and out["stopped"] is None
    assert 30 in clock.slept                                         # the backoff of lookup_one


def test_three_codes_in_a_row_that_stay_rate_limited_stop_the_run_after_writing_what_it_has():
    batches, write = collector()
    clock = Clock()
    cs = codes(10)
    scripted = {c: [RATE_LIMITED] * 10 for c in cs[4:7]}
    out = lib.run_lookups(cs, write, get=Network(scripted), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert "rate limited" in out["stopped"] and out["written"] == 4 and [x["code"] for b in batches for x in b] == cs[:4]
    assert out["asked"] == 7


def test_a_single_rate_limited_code_is_skipped_without_stopping_and_is_not_written():
    batches, write = collector()
    clock = Clock()
    cs = codes(6)
    out = lib.run_lookups(cs, write, get=Network({cs[2]: [RATE_LIMITED] * 10}), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert out["stopped"] is None and out["written"] == 5 and cs[2] not in [x["code"] for b in batches for x in b]


def test_the_time_budget_stops_the_run_and_the_partial_batch_is_still_written():
    batches, write = collector()
    clock = Clock()
    out = lib.run_lookups(codes(100), write, get=Network(), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, budget_seconds=30, log=lambda *_: None)
    assert out["stopped"] == "time budget" and 0 < out["written"] < 100 and out["written"] == out["asked"]
    assert sum(len(b) for b in batches) == out["written"]


def test_an_unclear_answer_that_is_not_a_rate_limit_is_written_as_unconfirmed_and_counted():
    batches, write = collector()
    clock = Clock()
    cs = codes(4)
    odd = (404, {"status": 0, "status_verbose": "something new OFF may add"}, None, None)
    out = lib.run_lookups(cs, write, get=Network({cs[1]: [odd]}), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert out["unconfirmed"] == 1 and out["answered_clearly"] == 3 and out["written"] == 4
    assert [x["status"] for b in batches for x in b][1] == "unconfirmed"


def test_a_full_day_of_500_codes_with_8_percent_rate_limits_costs_about_47_minutes_and_all_get_answered():
    # the 8% is the rate measured in the first test from Databricks (2026-10-21); the retry of lookup_one clears each one here as it did not need to in the second test
    random.seed(20261021)
    scripted = {c: [RATE_LIMITED] for c in codes(500) if random.random() < 0.08}
    batches, write = collector()
    clock = Clock()
    per_request = 0.3

    class Slow(Network):
        def __call__(self, url):
            clock.t += per_request
            return super().__call__(url)

    out = lib.run_lookups(codes(500), write, get=Slow(scripted), sleep=clock.sleep, monotonic=clock.monotonic, now=fixed_now, log=lambda *_: None)
    assert out["written"] == 500 and out["answered_clearly"] == 500 and out["stopped"] is None
    assert out["retries"] == len(scripted) and 25 <= out["retries"] <= 55
    assert 40 * 60 < out["seconds"] < lib.DEFAULT_BUDGET_MINUTES * 60               # long, but inside the budget


# --- the notebook and the job --------------------------------------------------------------------------------------------------------------------

def test_the_notebook_skips_answered_codes_writes_in_batches_and_never_retries_automatically():
    text = (HERE.parent / "notebooks" / "reconcile_lookup.py").read_text(encoding="utf-8")
    assert "generated_at" in text and "select_pending" in text and "write_batch" in text and "run_lookups" in text
    assert "MAX_UNCONFIRMED_PER_CYCLE" in text and "evidence_source = '{rl.EVIDENCE_API}'" in text
    assert "import duckdb" not in text and "dbutils.secrets.get(SCOPE, \"healthchecks_reconcile_lookup_ping_url\")" in text
    assert "ping(\"/fail\"" in text


def test_the_lookup_job_runs_daily_after_the_capture_window_without_retry_and_with_an_outer_limit():
    import yaml
    res = HERE.parents[1] / "p3_delivery" / "resources" / "reconcile_job.yml"
    job = yaml.safe_load(res.read_text(encoding="utf-8"))["resources"]["jobs"]["reconcile_lookup"]
    assert job["name"] == "packsense-reconcile-lookup" and job["max_concurrent_runs"] == 1
    assert job["schedule"]["quartz_cron_expression"] == "0 0 10 * * ?" and job["schedule"]["pause_status"] == "UNPAUSED"
    assert job["timeout_seconds"] >= lib.DEFAULT_BUDGET_MINUTES * 60 + 600           # the outer limit is past the notebook's own budget
    (task,) = job["tasks"]
    assert task["disable_auto_optimization"] is True and (res.parent / task["notebook_task"]["notebook_path"]).resolve().is_file()
    for name in task["notebook_task"]["base_parameters"]:
        assert not any(w in name.lower() for w in ("token", "password", "key", "hmac")), name
