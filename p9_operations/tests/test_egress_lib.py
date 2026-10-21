"""p9_operations/egress_lib.py: the monthly egress check, with the network faked (the status rules are code paths, not data)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import egress_lib as lib  # noqa: E402


def by_name(fragment):
    (s,) = [s for s in lib.SERVICES if fragment in s.name]
    return s


def test_every_outside_service_the_pipeline_needs_is_listed_with_a_light_request():
    names = " | ".join(s.name for s in lib.SERVICES)
    for needed in ("delta index", "taxonomy", "product API", "Hugging Face", "Backblaze", "PyPI", "healthchecks"):
        assert needed in names, needed
    assert all(s.url.startswith("https://") for s in lib.SERVICES) and len(lib.SERVICES) == 7
    assert "fields=code,status" in by_name("product API").url                     # one product, two fields: nothing heavy
    assert by_name("taxonomy").method == "HEAD"
    assert all("token" not in s.url.lower() and "key" not in s.url.lower() for s in lib.SERVICES)


@pytest.mark.parametrize("fragment,status,body,error,ok", [
    ("delta index", 200, "", None, True),
    ("delta index", 404, "", None, False),
    ("delta index", None, "", "TimeoutError: timed out", False),
    ("product API", 200, '{"code":"3017620422003","status": 1}', None, True),
    ("product API", 200, '{"code":"3017620422003","status":0}', None, False),
    ("product API", 429, "", None, True),                                         # busy, but reachable
    ("Backblaze", 403, "", None, True),                                           # unauthenticated: reachable
    ("Backblaze", 400, "", None, True),
    ("Backblaze", 500, "", None, False),
    ("PyPI", 403, "", None, False),                                               # a proxy blocking the domain would look like this
    ("Hugging Face", None, "", "URLError: no route", False),
])
def test_the_status_rules(fragment, status, body, error, ok):
    got, detail = lib.judge(by_name(fragment), status, body, error)
    assert got is ok and detail


def test_a_failure_detail_names_what_went_wrong_and_nothing_secret():
    ok, detail = lib.judge(by_name("PyPI"), None, "", "ConnectionResetError: " + "x" * 500)
    assert not ok and detail.startswith("not reachable") and len(detail) < 160


def test_check_all_makes_one_request_per_service_pauses_between_them_and_summarises():
    calls, slept = [], []

    def fetcher(service):
        calls.append(service.name)
        return (200, '{"status":1}', None) if "product API" in service.name else ((403, "", None) if "Backblaze" in service.name else (200, "", None))

    results = lib.check_all(fetcher=fetcher, sleep=slept.append, pause=2.0)
    assert calls == [s.name for s in lib.SERVICES] and slept == [2.0] * (len(lib.SERVICES) - 1)
    assert all(r["ok"] for r in results) and lib.summary(results) == "all 7 outside services reachable"


def test_the_summary_names_every_failing_service():
    def fetcher(service):
        return (None, "", "TimeoutError: timed out") if "PyPI" in service.name or "Hugging Face" in service.name else (200, '{"status":1}', None)

    results = lib.check_all(fetcher=fetcher, sleep=lambda _s: None)
    text = lib.summary(results)
    assert text.startswith("2 of 7 outside services failed") and "PyPI" in text and "Hugging Face" in text and "delta index" not in text


def test_the_notebook_goes_red_and_pings_fail_on_any_failure_and_uses_no_secret_but_the_ping_url():
    text = (HERE.parent / "notebooks" / "egress_check.py").read_text(encoding="utf-8")
    assert 'ping("/fail", text)' in text and "raise RuntimeError(text)" in text and "lib.check_all()" in text
    assert text.count("dbutils.secrets.get") == 1 and "healthchecks_egress_ping_url" in text


def test_the_egress_job_runs_monthly_without_retry():
    import yaml
    res = HERE.parents[1] / "p3_delivery" / "resources" / "reconcile_job.yml"
    job = yaml.safe_load(res.read_text(encoding="utf-8"))["resources"]["jobs"]["egress_check"]
    assert job["name"] == "packsense-egress-check" and job["schedule"]["quartz_cron_expression"] == "0 0 5 1 * ?"
    (task,) = job["tasks"]
    assert task["disable_auto_optimization"] is True and (res.parent / task["notebook_task"]["notebook_path"]).resolve().is_file()
