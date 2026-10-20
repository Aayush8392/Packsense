"""The reconciliation DAG's logic (p9_operations/airflow/reconcile_dag_lib.py) on real OFF answers (fixtures/off_api_responses.json) with the network faked."""
import ast
import datetime as dt
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
AIRFLOW = HERE.parent / "airflow"
sys.path.insert(0, str(AIRFLOW))
import reconcile_dag_lib as lib  # noqa: E402
import existence_lib as rl  # noqa: E402

API = {r["code"]: r for r in json.loads((HERE / "fixtures" / "off_api_responses.json").read_text(encoding="utf-8"))["responses"]}
NOW = dt.datetime(2026, 10, 20, 17, 0, tzinfo=dt.timezone.utc)


def fixed_now():
    return NOW


def real_get(url):
    """The network, replaced by the recorded real answer for the code in the URL."""
    code = url.split("/product/")[1].split(".json")[0]
    r = API[code]
    return r["http"], {"status": r["status"], "status_verbose": r["status_verbose"]}, None, None


class Script:
    """A fake `get` that plays a list of answers in order and records the calls."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url):
        self.calls.append(url)
        return self.answers.pop(0)


def no_sleep(_):
    return None


RATE_LIMITED = (429, None, None, None)


# --- one lookup ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("code,status", [("3614790000309", "moved_other_type"), ("9781338214611", "confirmed_not_found"), ("5411883501440", "confirmed_exists"),
                                         ("0000000000000", "invalid_code")])
def test_a_clear_answer_is_returned_at_once_without_a_retry(code, status):
    slept = []
    line, limited = lib.lookup_one(code, get=real_get, sleep=slept.append, now=fixed_now)
    assert line["status"] == status and line["checked_at"] == "2026-10-20T17:00:00Z" and limited is False and slept == []


def test_a_rate_limit_is_retried_with_a_growing_pause_and_the_later_answer_wins():
    ok = real_get(rl.api_url("5411883501440"))
    get, slept = Script([RATE_LIMITED, RATE_LIMITED, ok]), []
    line, limited = lib.lookup_one("5411883501440", get=get, sleep=slept.append, now=fixed_now)
    assert line["status"] == "confirmed_exists" and limited is False and slept == [30, 60] and len(get.calls) == 3


def test_retry_after_from_off_is_honoured_up_to_the_cap():
    get, slept = Script([(429, None, None, 7), (429, None, None, 9999), (200, {"status": 1, "status_verbose": "product found"}, None, None)]), []
    lib.lookup_one("1", get=get, sleep=slept.append, now=fixed_now)
    assert slept == [7, lib.MAX_BACKOFF]


def test_a_code_that_stays_rate_limited_after_every_attempt_is_flagged_and_unconfirmed():
    get, slept = Script([RATE_LIMITED] * lib.MAX_ATTEMPTS), []
    line, limited = lib.lookup_one("1", get=get, sleep=slept.append, now=fixed_now)
    assert limited is True and line["status"] == "unconfirmed" and slept == [30, 60, 120, 240] and len(get.calls) == lib.MAX_ATTEMPTS


def test_a_timeout_is_retried_but_is_not_a_rate_limit():
    get, slept = Script([(None, None, "TimeoutError: timed out", None)] * lib.MAX_ATTEMPTS), []
    line, limited = lib.lookup_one("1", get=get, sleep=slept.append, now=fixed_now)
    assert line["status"] == "unconfirmed" and "request failed" in line["detail"] and limited is False and len(get.calls) == lib.MAX_ATTEMPTS


def test_an_answer_retrying_cannot_improve_is_not_retried():
    get = Script([(404, {"status": 0, "status_verbose": "something new OFF may add"}, None, None)])
    line, limited = lib.lookup_one("1", get=get, sleep=no_sleep, now=fixed_now)
    assert line["status"] == "unconfirmed" and "unrecognised" in line["detail"] and limited is False and len(get.calls) == 1


# --- a batch ------------------------------------------------------------------------------------------------------------------------------

REAL_CODES = list(API)[:6]


def test_a_batch_writes_one_file_per_code_pauses_between_lookups_and_resumes(tmp_path):
    slept, calls = [], []

    def get(url):
        calls.append(url)
        return real_get(url)

    first = lib.run_batch(REAL_CODES, str(tmp_path), get=get, sleep=slept.append, now=fixed_now)
    assert first == {"looked_up": 6, "already_done": 0, "codes": 6} and len(list(tmp_path.glob("*.json"))) == 6
    assert slept == [rl.API_PAUSE_SECONDS] * 6
    again = lib.run_batch(REAL_CODES + [list(API)[6]], str(tmp_path), get=get, sleep=slept.append, now=fixed_now)
    assert again == {"looked_up": 1, "already_done": 6, "codes": 7} and len(calls) == 7             # only the new code was asked


def test_three_rate_limited_codes_in_a_row_stop_the_batch_and_leave_no_files_for_them(tmp_path):
    get = Script([real_get(rl.api_url(REAL_CODES[0]))] + [RATE_LIMITED] * (lib.MAX_ATTEMPTS * 3))
    with pytest.raises(lib.RateLimited):
        lib.run_batch(REAL_CODES, str(tmp_path), get=get, sleep=no_sleep, now=fixed_now)
    assert [p.stem for p in tmp_path.glob("*.json")] == [REAL_CODES[0]]


def test_a_rate_limited_code_followed_by_a_good_one_does_not_stop_the_batch(tmp_path):
    answers = ([RATE_LIMITED] * lib.MAX_ATTEMPTS + [real_get(rl.api_url(REAL_CODES[1]))]
               + [RATE_LIMITED] * lib.MAX_ATTEMPTS + [real_get(rl.api_url(REAL_CODES[3]))])
    out = lib.run_batch([REAL_CODES[0], REAL_CODES[1], REAL_CODES[2], REAL_CODES[3]], str(tmp_path), get=Script(answers), sleep=no_sleep, now=fixed_now)
    assert out["looked_up"] == 2 and sorted(p.stem for p in tmp_path.glob("*.json")) == sorted([REAL_CODES[1], REAL_CODES[3]])


def test_collect_gives_one_line_per_candidate_in_order_and_marks_the_unanswered(tmp_path):
    lib.run_batch(REAL_CODES[:3], str(tmp_path), get=real_get, sleep=no_sleep, now=fixed_now)
    lines = lib.collect(REAL_CODES[:5], str(tmp_path), now=fixed_now)
    assert [x["code"] for x in lines] == REAL_CODES[:5]
    assert [x["status"] for x in lines[3:]] == ["unconfirmed", "unconfirmed"] and lines[3]["detail"] == "not looked up in this run"
    assert rl.parse_results(lib.to_jsonl(lines)) == lines                         # exactly what the Databricks loader accepts


def test_chunking_keeps_every_code_once_in_batches_of_at_most_the_batch_size():
    codes = [str(i) for i in range(2345)]
    batches = lib.chunk(codes)
    assert [len(b) for b in batches] == [100] * 23 + [45] and [c for b in batches for c in b] == codes
    assert len(batches) < 1024                                                     # Airflow refuses to map over more than 1,024 items by default


# --- the network helper and the landing volume --------------------------------------------------------------------------------------------

def test_http_get_returns_errors_as_values(monkeypatch):
    def boom(req, timeout=None):
        raise urllib.error.URLError("no route")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    status, body, error, retry = lib.http_get("https://example.invalid/x")
    assert status is None and body is None and "URLError" in error


def test_http_get_reads_a_404_body_and_the_retry_after_header(monkeypatch):
    def refuse(req, timeout=None):
        assert req.get_header("User-agent") == lib.USER_AGENT
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {"Retry-After": "12"}, io.BytesIO(b'{"x": 1}'))
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    assert lib.http_get("https://example.invalid/x") == (429, {"x": 1}, None, 12)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.content = body if isinstance(body, bytes) else b""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.headers, self.responses, self.calls = {}, list(responses), []

    def get(self, url, **kw):
        self.calls.append(("GET", url, None))
        return FakeResponse(*self.responses.pop(0))

    def put(self, url, **kw):
        self.calls.append(("PUT", url, kw.get("data")))
        return FakeResponse(*self.responses.pop(0))


def test_the_landing_volume_is_reached_through_the_files_api_with_the_right_urls():
    listing = {"contents": [{"name": "2026-10-19.json", "is_directory": False}, {"name": "old", "is_directory": True}]}
    s = FakeSession([(200, listing), (200, b"{}"), (204, b""), (404, {})])
    land = lib.Landing("dbc-example.cloud.databricks.com", "tok", base="/Volumes/workspace/packsense/landing/", session=s)
    assert s.headers["Authorization"] == "Bearer tok"
    assert land.list("reconcile/candidates") == ["2026-10-19.json"]
    assert land.read("reconcile/candidates/2026-10-19.json") == b"{}"
    land.write("reconcile/results/2026-10-19.jsonl", b"x")
    assert land.list("reconcile/nothing") == []
    urls = [c[1] for c in s.calls]
    assert urls[0] == "https://dbc-example.cloud.databricks.com/api/2.0/fs/directories/Volumes/workspace/packsense/landing/reconcile/candidates"
    assert urls[1].endswith("/api/2.0/fs/files/Volumes/workspace/packsense/landing/reconcile/candidates/2026-10-19.json")
    assert urls[2].endswith("/reconcile/results/2026-10-19.jsonl?overwrite=true") and s.calls[2][2] == b"x"


def test_the_newest_candidate_list_is_the_latest_snapshot_date():
    assert lib.newest_candidates_file(["2026-10-12.json", "2026-10-19.json", "notes.txt", "2026-10-05.json"]) == "2026-10-19.json"
    assert lib.newest_candidates_file([]) is None and lib.newest_candidates_file(["x.json"]) is None


# --- the DAG file (Airflow itself is not installed here: the file is read, not run) -------------------------------------------------------------

def test_the_dag_is_wired_as_designed_and_holds_no_secret():
    src = (AIRFLOW / "dags" / "packsense_reconcile.py").read_text(encoding="utf-8")
    ast.parse(src)
    assert 'POOL = "off_api"' in src and "pool=POOL" in src
    assert 'schedule="0 9 * * 2"' in src and "max_active_runs=1" in src and "catchup=False" in src
    assert "retries=4" in src and "execution_timeout" in src and 'mode="reschedule"' in src
    assert ".partial(" in src and ".expand(batch=batches_of(plan))" in src               # mapped over BATCHES, never over single codes
    assert 'plan["batches"])' not in src.split("def batches_of")[1].split("upload(plan")[1] and "expand(batch=plan[" not in src    # Airflow 3 refuses to map over one key of an XCom
    assert 'os.environ["PACKSENSE_PIPELINE_TOKEN"]' in src and "dapi" not in src
    assert '"max_codes": 0' in src and "get_current_context" in src                    # a drill can be limited to a few codes
    assert 'trigger_rule="all_done"' in src                                             # the upload runs even if a batch gave up
    compose = (AIRFLOW / "docker-compose.override.yaml").read_text(encoding="utf-8")
    assert ":ro" in compose and "dapi" not in compose
