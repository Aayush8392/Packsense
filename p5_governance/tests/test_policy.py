"""Tests for the nightly policy tests: how an attempt is judged, that the checks file agrees with grants.yml in both directions, that the
adapters build only probe objects, that the bundle wires every job to its identity, and that the drift comparison finds a planted difference."""
import re
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
sys.path.insert(0, str(P5 / "policy"))
import grants_lib as gl  # noqa: E402
import grants_live as live  # noqa: E402
import policy_lib as pl  # noqa: E402
import policy_runners as pr  # noqa: E402

GRANTS = gl.load_spec()
CHECKS = pl.load_checks()


class PermissionDenied(Exception):       # the SDK's class name is what the matcher sees
    pass


class NotFound(Exception):
    pass


def raising(exc):
    def f():
        raise exc
    return f


DENY = {"name": "d", "kind": "deny"}
ALLOW = {"name": "a", "kind": "allow"}


# --- judging an attempt ---------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("message", [
    "[INSUFFICIENT_PERMISSIONS] Insufficient privileges: User does not have USE SCHEMA on Schema 'workspace.packsense_bronze'. SQLSTATE: 42501",
    "An error occurred while calling ListSecrets. PERMISSION_DENIED: User 05620ebf-cd4d is not allowed",
    "(com.databricks.sql.managedcatalog.acl.UnauthorizedAccessException) PERMISSION_DENIED: User does not have CREATE SCHEMA on Catalog 'workspace'.",
    "[Errno 13] Permission denied: '/Volumes/workspace/packsense/landing/_policy_probe.txt'",   # a file write to a volume the identity cannot write
])
def test_the_real_denial_messages_seen_on_dev_are_recognised(message):
    assert pl.is_denied(RuntimeError(message))


@pytest.mark.parametrize("message", ["[TABLE_OR_VIEW_NOT_FOUND] The table does not exist", "syntax error at or near", "connection reset", "timed out"])
def test_other_errors_are_not_denials(message):
    assert not pl.is_denied(RuntimeError(message))


def test_a_deny_check_passes_only_on_a_permission_error():
    assert pl.evaluate(DENY, raising(PermissionDenied("nope")))["status"] == "PASS"
    assert pl.evaluate(DENY, raising(RuntimeError("PERMISSION_DENIED: x")))["status"] == "PASS"
    assert pl.evaluate(DENY, lambda: None)["status"] == "FAIL"                                  # it was allowed
    assert pl.evaluate(DENY, raising(NotFound("table does not exist")))["status"] == "ERROR"    # denied for the wrong reason proves nothing


def test_an_allow_check_passes_only_on_success():
    assert pl.evaluate(ALLOW, lambda: None)["status"] == "PASS"
    assert pl.evaluate(ALLOW, raising(PermissionDenied("nope")))["status"] == "FAIL"
    assert pl.evaluate(ALLOW, raising(RuntimeError("boom")))["status"] == "ERROR"


def test_cleanup_runs_after_a_check_that_unexpectedly_succeeded_and_a_failing_cleanup_is_harmless():
    log = []
    checks = [{"name": "c1", "kind": "deny", "action": "create_table", "schema": "workspace.s"},
              {"name": "c2", "kind": "allow", "action": "read_table", "table": "workspace.s.t"}]

    def cleanup_for(c):
        def f():
            log.append(c["name"])
            if c["name"] == "c1":
                raise RuntimeError("nothing to drop")
        return f

    results = pl.run_checks(checks, lambda c: (lambda: None), cleanup_for)
    assert log == ["c1", "c2"]
    assert [r["status"] for r in results] == ["FAIL", "PASS"]


def test_the_summary_lists_only_what_did_not_pass_and_never_a_value():
    results = [{"name": "ok", "kind": "deny", "status": "PASS", "detail": "denied"},
               {"name": "bad", "kind": "deny", "status": "FAIL", "detail": "ALLOWED, but this identity must be denied"}]
    ok, text = pl.summarise("packsense-gold", results)
    assert not ok and "1/2 checks passed" in text and "FAIL deny bad" in text and "ok:" not in text


# --- the checks file against grants.yml ----------------------------------------------------------------------------------------

def test_the_checks_file_validates_and_every_identity_is_a_role_of_grants_yml():
    for ident, body in CHECKS["identities"].items():
        p = GRANTS["principals"][ident]
        assert body["runner"] == ("notebook" if p["kind"] == "service_principal" else "sdk"), ident


def test_every_non_admin_role_has_checks():
    roles = {r for r in GRANTS["principals"] if r != "admin"}
    assert roles == set(CHECKS["identities"]), "a role of grants.yml without policy checks (or the reverse)"


def test_every_check_agrees_with_grants_yml_in_both_directions():
    for ident, body in CHECKS["identities"].items():
        for c in body["checks"]:
            allowed = pl.expected_allowed(ident, c, GRANTS)
            assert allowed == (c["kind"] == "allow"), f"{ident} / {c['name']}: grants.yml says {'allowed' if allowed else 'denied'}"


def test_a_check_that_contradicts_grants_yml_is_caught():
    bad = {"name": "x", "kind": "allow", "action": "read_table", "table": "workspace.packsense_bronze.bronze_manifest"}
    assert not pl.expected_allowed("packsense-gold", bad, GRANTS)


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["identities"]["analyst"]["checks"].clear(), "needs at least one deny check"),
    (lambda s: s["identities"]["analyst"]["checks"][0].update({"action": "drop_everything"}), "action one of"),
    (lambda s: s["identities"]["analyst"]["checks"][1].update({"table": "x; DROP TABLE y"}), "plain object name"),
    (lambda s: s["identities"]["analyst"]["checks"][1].pop("table"), "needs table"),
])
def test_a_bad_checks_file_is_refused(mutate, message):
    import copy
    bad = copy.deepcopy(CHECKS)
    mutate(bad)
    with pytest.raises(pl.ChecksError, match=message):
        pl.validate_checks(bad)


# --- the adapters ----------------------------------------------------------------------------------------------------------------

def test_every_statement_built_touches_only_a_probe_object_or_reads_a_listed_table():
    for ident, body in CHECKS["identities"].items():
        for c in body["checks"]:
            if c["action"] in ("create_table", "create_schema", "create_volume"):
                stmt, clean = pr.sql_attempt(c), pr.sql_cleanup(c)
                assert pl.PROBE in stmt and clean and pl.PROBE in clean and clean.startswith("DROP ")
            elif c["action"] == "read_table":
                assert pr.sql_attempt(c) == f"SELECT 1 FROM {c['table']} LIMIT 1"
            elif c["action"] == "upload_file":
                assert pr.volume_path(c["volume"]).endswith(f"/{pl.PROBE}.txt")


class FakeSpark:
    def __init__(self, fail=()):
        self.log, self.fail = [], fail

    def sql(self, stmt):
        self.log.append(stmt)
        if any(f in stmt for f in self.fail):
            raise RuntimeError("[INSUFFICIENT_PERMISSIONS] no. SQLSTATE: 42501")
        return NS(collect=lambda: [("x",)])


def test_the_notebook_runner_attempts_and_cleans_up_as_planned():
    sp = FakeSpark(fail=("packsense_bronze",))
    run = pr.NotebookRunner(sp, NS(secrets=NS(list=lambda scope: (_ for _ in ()).throw(RuntimeError("PERMISSION_DENIED")))))
    checks = CHECKS["identities"]["packsense-gold"]["checks"]
    results = pl.run_checks(checks, run.attempt_for, run.cleanup_for)
    by = {r["name"]: r["status"] for r in results}
    assert by["cannot read bronze"] == "PASS" and by["cannot read the bronze scope"] == "PASS"
    assert any(s.startswith("DROP TABLE IF EXISTS workspace.packsense_gold._policy_probe") for s in sp.log)


def test_the_sdk_runner_maps_each_action_to_one_api_call_and_cleans_up():
    calls = []

    class W:
        catalogs = NS(get=lambda name: calls.append(("catalog", name)))
        tables = NS(get=lambda full_name: calls.append(("table", full_name)))
        secrets = NS(list_secrets=lambda scope: calls.append(("secrets", scope)) or [])
        files = NS(upload=lambda path, f, overwrite: calls.append(("upload", path)), delete=lambda path: calls.append(("delete", path)))
        volumes = NS(create=lambda **kw: calls.append(("volume", kw["name"])), delete=lambda name: calls.append(("vdelete", name)))
        statement_execution = NS(execute_statement=lambda **kw: calls.append(("sql", kw["statement"])) or NS(
            status=NS(state=NS(value="SUCCEEDED")), result=NS(data_array=[["en:india"]])))

    run = pr.SdkRunner(W())
    for c in CHECKS["identities"]["pipeline-user"]["checks"] + CHECKS["identities"]["analyst"]["checks"]:
        run.attempt_for(c)()
        run.cleanup_for(c)()
    kinds = {k for k, _ in calls}
    assert {"catalog", "table", "secrets", "upload", "delete", "volume", "vdelete", "sql"} <= kinds
    assert all(pl.PROBE in v for k, v in calls if k in ("upload", "delete", "volume", "vdelete"))


# --- the bundle ------------------------------------------------------------------------------------------------------------------

BUNDLE = yaml.safe_load((P5 / "databricks.yml").read_text(encoding="utf-8"))
JOBS = yaml.safe_load((P5 / "policy" / "resources" / "policy_jobs.yml").read_text(encoding="utf-8"))["resources"]["jobs"]


def test_each_principal_job_runs_as_the_identity_it_tests_and_the_principal_can_read_the_notebooks():
    permitted = {p["service_principal_name"] for p in BUNDLE["permissions"]}
    seen = set()
    for key, job in JOBS.items():
        if "run_as" not in job:
            continue
        sp = job["run_as"]["service_principal_name"]
        (task,) = job["tasks"]
        assert task["notebook_task"]["base_parameters"]["expected_id"] == sp
        assert task["disable_auto_optimization"] is True, "a retry would mask a red check"
        assert sp in permitted
        seen.add(task["notebook_task"]["base_parameters"]["identity"])
    assert seen == {r for r, b in CHECKS["identities"].items() if b["runner"] == "notebook"}


def test_the_admin_job_starts_every_principal_job_tests_both_users_checks_drift_and_reports_last():
    tasks = {t["task_key"]: t for t in JOBS["policy"]["tasks"]}
    started = {t["run_job_task"]["job_id"] for t in tasks.values() if "run_job_task" in t}
    assert started == {"${resources.jobs.%s.id}" % k for k, j in JOBS.items() if "run_as" in j}
    users = {t["notebook_task"]["base_parameters"]["identity"] for t in tasks.values() if "token_key" in t.get("notebook_task", {}).get("base_parameters", {})}
    assert users == {r for r, b in CHECKS["identities"].items() if b["runner"] == "sdk"}
    assert "grants_drift" in tasks
    report = tasks["report"]
    assert report["run_if"] == "ALL_DONE"
    assert {d["task_key"] for d in report["depends_on"]} == set(tasks) - {"report"}
    results = report["notebook_task"]["base_parameters"]["results"]
    assert set(re.findall(r"tasks\.(\w+)\.result_state", results)) == set(tasks) - {"report"}


def test_the_schedule_is_live_pinging_and_no_secret_is_a_job_parameter():
    assert BUNDLE["variables"]["policy_pause"]["default"] == "UNPAUSED"
    assert BUNDLE["variables"]["ping"]["default"] == "true"
    text = (P5 / "policy" / "resources" / "policy_jobs.yml").read_text(encoding="utf-8")
    assert not re.search(r"(secret|password|token)\s*:", text.replace("token_key", ""), re.I)


def test_every_notebook_the_bundle_names_exists():
    for job in JOBS.values():
        for t in job["tasks"]:
            nb = t.get("notebook_task", {}).get("notebook_path")
            if nb:
                assert (P5 / "policy" / "resources" / nb).resolve().is_file(), nb


# --- the drift comparison --------------------------------------------------------------------------------------------------------

def _fake_workspace(extra=False, drop=False):
    """A fake workspace whose live state equals grants.yml (resolved through ids), optionally with one extra or one missing grant."""
    spec = GRANTS
    ids = {r: f"id-{r}" for r in spec["principals"]}
    want, _ = gl.expected_grants(spec, ids)
    if drop:
        want.discard(("table", "workspace.packsense_silver.silver_manifest", "id-packsense-gold", "SELECT"))
    if extra:
        want.add(("schema", "workspace.packsense_bronze", "id-packsense-gold", "SELECT"))

    def privs(kind, name):
        by = {}
        for k, n, p, pr_ in want:
            if (k, n) == (kind, name):
                by.setdefault(p, []).append(NS(value=pr_))
        return NS(privilege_assignments=[NS(principal=p, privileges=v) for p, v in by.items()])

    schemas = sorted({s["name"].split(".")[1] for s in spec["securables"] if s["type"] == "schema"})
    volumes = {s["name"] for s in spec["securables"] if s["type"] == "volume"}
    tables = {s["name"] for s in spec["securables"] if s["type"] == "table"}
    acls = {scope: [NS(principal=ids[r], permission=NS(value=perm)) for r, perm in a.items()] for scope, a in spec["secret_scopes"].items()}
    w = NS(
        service_principals=NS(list=lambda: [NS(display_name=p["name"], application_id=ids[r]) for r, p in spec["principals"].items() if p["kind"] == "service_principal"]),
        current_user=NS(me=lambda: NS(user_name=ids["admin"])),
        config=NS(host="https://example.invalid"),
        grants=NS(get=lambda securable_type, full_name: privs(securable_type, full_name)),
        schemas=NS(list=lambda catalog_name: [NS(name=s) for s in schemas]),
        volumes=NS(list=lambda catalog_name, schema_name: [NS(full_name=v) for v in volumes if v.split(".")[1] == schema_name]),
        tables=NS(list=lambda catalog_name, schema_name: [NS(full_name=t) for t in tables if t.split(".")[1] == schema_name]),
        secrets=NS(list_scopes=lambda: [NS(name=s) for s in acls], list_acls=lambda scope: acls[scope]),
    )
    return w, ids


def _compare(w, ids):
    env = {}
    import grants_live
    original = grants_live.resolve_principals
    grants_live.resolve_principals = lambda w_, spec, environ: (ids, {v: k for k, v in ids.items()})
    try:
        return live.compare(w, GRANTS, env)
    finally:
        grants_live.resolve_principals = original


def test_the_drift_comparison_is_clean_when_live_equals_the_file():
    w, ids = _fake_workspace()
    r = _compare(w, ids)
    assert r["clean"], live.describe(r)


def test_the_drift_comparison_reports_a_planted_extra_and_a_planted_missing_grant():
    w, ids = _fake_workspace(extra=True)
    r = _compare(w, ids)
    assert not r["clean"] and len(r["extra_g"]) == 1 and "EXTRA" in live.describe(r)
    w, ids = _fake_workspace(drop=True)
    r = _compare(w, ids)
    assert not r["clean"] and len(r["missing_g"]) == 1 and "MISSING" in live.describe(r)


def test_a_role_that_cannot_be_resolved_makes_the_check_red():
    w, ids = _fake_workspace()
    ids["analyst"] = None
    r = _compare(w, ids)
    assert r["unresolved"] == ["analyst"] and not r["clean"]
