"""Every deny check must go RED when its action is allowed, and every check must really attempt the action it names.

The nightly job proves the mechanism live (planted violations turned the right tasks red). This test closes the gap for every individual check, offline:
it drives each check's attempt against a fake identity that is allowed to do EVERYTHING and expects the deny check to FAIL, and against a fake that is
denied everything and expects the deny check to PASS and the allow checks to FAIL. It also asserts that the attempt touched the object the check names, so a check
whose attempt silently does nothing (and could therefore never fail) is caught."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
sys.path.insert(0, str(P5 / "policy"))
import policy_lib as pl  # noqa: E402
import policy_runners as pr  # noqa: E402

CHECKS = pl.load_checks()["identities"]
ALL = [(ident, c) for ident, body in CHECKS.items() for c in body["checks"]]
DENY = [(i, c) for i, c in ALL if c["kind"] == "deny"]
ALLOW = [(i, c) for i, c in ALL if c["kind"] == "allow"]


class PermissionDenied(Exception):
    pass


def check_id(item):
    return f"{item[0]}:{item[1]['name']}"


def target_of(check):
    return check.get("table") or check.get("schema") or check.get("scope") or check.get("volume") or check.get("catalog")


class Recorder:
    """An identity that either may do anything (deny=False) or nothing (deny=True); records what each attempt touched."""

    def __init__(self, deny: bool):
        self.deny, self.touched = deny, []

    def _do(self, what):
        self.touched.append(what)
        if self.deny:
            raise PermissionDenied("[INSUFFICIENT_PERMISSIONS] denied. SQLSTATE: 42501")

    # notebook side
    @property
    def spark(self):
        return NS(sql=lambda stmt: NS(collect=lambda: (self._do(stmt), [("x",)])[1]))

    @property
    def dbutils(self):
        return NS(secrets=NS(list=lambda scope: self._do(f"secrets:{scope}")))

    # sdk side
    @property
    def w(self):
        outer = self
        return NS(
            catalogs=NS(get=lambda name: outer._do(f"catalog:{name}")),
            tables=NS(get=lambda full_name: outer._do(f"table:{full_name}")),
            secrets=NS(list_secrets=lambda scope: (outer._do(f"secrets:{scope}"), [])[1]),
            files=NS(upload=lambda path, f, overwrite: outer._do(f"file:{path}"), delete=lambda path: None),
            volumes=NS(create=lambda **kw: outer._do(f"volume:{kw['catalog_name']}.{kw['schema_name']}.{kw['name']}"), delete=lambda name: None),
            statement_execution=NS(execute_statement=lambda **kw: (outer._do(kw["statement"]), NS(
                status=NS(state=NS(value="SUCCEEDED")), result=NS(data_array=[["en:india"]])))[1]),
        )


@pytest.fixture
def volume_in_tmp():
    yield
    if "open" in vars(pr):
        del pr.open


class _Ctx:
    def __init__(self, path, rec):
        rec._do(f"file:{path}")

    def __enter__(self):
        return NS(write=lambda text: None)

    def __exit__(self, *a):
        return False


def attempt(ident, check, rec):
    pr.open = lambda path, mode="r", **kw: _Ctx(path, rec)       # a module-level name beats the builtin: no real file is ever written
    runner = (pr.NotebookRunner(rec.spark, rec.dbutils) if CHECKS[ident]["runner"] == "notebook" else pr.SdkRunner(rec.w))
    return runner.attempt_for(check)


def touched_target(check, touched):
    t = target_of(check)
    if check["action"] == "upload_file":
        cat, sch, vol = t.split(".")
        return any(x.startswith("file:") and f"/Volumes/{cat}/{sch}/{vol}/" in x for x in touched)
    return any(t in x for x in touched)


@pytest.mark.parametrize("item", DENY, ids=check_id)
def test_a_deny_check_goes_red_when_its_action_is_allowed(item, volume_in_tmp):
    ident, check = item
    rec = Recorder(deny=False)
    result = pl.evaluate(check, attempt(ident, check, rec))
    assert result["status"] == "FAIL" and "ALLOWED" in result["detail"], result


@pytest.mark.parametrize("item", DENY, ids=check_id)
def test_a_deny_check_passes_only_on_a_permission_error(item, volume_in_tmp):
    ident, check = item
    rec = Recorder(deny=True)
    result = pl.evaluate(check, attempt(ident, check, rec))
    assert result["status"] == "PASS", result


@pytest.mark.parametrize("item", ALL, ids=check_id)
def test_every_check_really_attempts_the_action_on_the_object_it_names(item, volume_in_tmp):
    ident, check = item
    rec = Recorder(deny=False)
    try:
        attempt(ident, check, rec)()
    except PermissionDenied:
        pass
    assert rec.touched, f"{check['name']}: the attempt did nothing, so the check could never fail"
    if check["action"] != "create_schema":
        assert touched_target(check, rec.touched), f"{check['name']}: the attempt never touched {target_of(check)}: {rec.touched}"


@pytest.mark.parametrize("item", ALLOW, ids=check_id)
def test_an_allow_check_goes_red_when_its_action_is_denied(item, volume_in_tmp):
    ident, check = item
    rec = Recorder(deny=True)
    result = pl.evaluate(check, attempt(ident, check, rec))
    assert result["status"] == "FAIL" and "denied" in result["detail"], result


def test_the_checks_file_still_has_deny_checks_for_every_action_type_that_a_policy_depends_on():
    actions = {c["action"] for _, c in DENY}
    assert {"read_table", "create_table", "create_schema", "list_secrets", "upload_file", "create_volume"} <= actions


def test_the_parametrised_tests_cover_every_check_in_the_file():
    assert len(ALL) == sum(len(b["checks"]) for b in CHECKS.values()) and len(DENY) + len(ALLOW) == len(ALL)
