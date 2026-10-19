"""Tests for the principal-secret rotation script: pure logic, the order of the steps with fakes, and that no value is ever printed."""
import base64
import datetime as dt
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))
import rotate_principal_secrets as rot  # noqa: E402

NEW_SECRET = "dose-NEW-secret-value-9f3a1c"     # a distinctive value: it must never appear in any output
ENTRIES = [
    {"name": "GH_TF_TOKEN", "expires": "2026-11-13"},
    {"name": "packsense-deployer-dev oauth secret", "expires": "2026-11-15"},
    {"name": "packsense-deployer oauth secret", "expires": "2026-11-15"},
    {"name": "packsense-gold-dev oauth secret", "expires": "2026-11-16", "note": "kept"},
    {"name": "packsense-gold oauth secret", "expires": "2026-11-16"},
]


class FakeDbx:
    def __init__(self, existing=2, verify_ok=True, log=None):
        self.log, self.existing, self.verify_ok = log if log is not None else [], existing, verify_ok
        self.deleted = []

    def sp_id(self, client_id):
        return "sp-1"

    def list_secrets(self, sp):
        return [(f"old{i}", "2026-11-15T00:00:00Z") for i in range(self.existing)]

    def create_secret(self, sp, lifetime):
        self.log.append(("create", lifetime))
        return "new1", NEW_SECRET, "2027-01-17T09:12:03.123Z"

    def verify(self, client_id, secret):
        self.log.append(("verify", secret == NEW_SECRET))
        return self.verify_ok

    def put_scope_secret(self, scope, value):
        self.log.append(("scope", scope))

    def delete_secret(self, sp, secret_id):
        self.log.append(("delete", secret_id))
        self.deleted.append(secret_id)


class FakeGh:
    def __init__(self, log, fail_put=False, same_updated_at=False, entries=None):
        self.log, self.fail_put, self.same = log, fail_put, same_updated_at
        self.value = json.dumps(ENTRIES if entries is None else entries)
        self.calls = 0

    def variable(self):
        return self.value

    def set_variable(self, value):
        self.log.append(("expiry",))
        self.value = value

    def secret_updated_at(self, env, name):
        self.calls += 1
        if self.same:
            return "t0"
        return "t0" if self.calls == 1 else "t1"

    def put_secret(self, env, name, value):
        if self.fail_put:
            raise RuntimeError("GitHub PUT -> HTTP 403")
        self.log.append(("github", env, name, value == NEW_SECRET))


def run(name="packsense-gold", dbx=None, gh=None, **kw):
    out = []
    log = []
    dbx = dbx or FakeDbx(log=log)
    gh = gh or FakeGh(dbx.log)
    kw.setdefault("lifetime_days", 90)
    kw.setdefault("keep_old", False)
    try:
        res = rot.rotate_one(name, dbx, gh, emit=out.append, sleep=lambda s: None, **kw)
    except Exception as e:  # noqa: BLE001
        res = e
    return res, out, dbx, gh


# ---- pure logic --------------------------------------------------------------------------------------------------------------

def test_lifetime_is_in_seconds_and_bounded():
    assert rot.lifetime_string(90) == "7776000s"
    for bad in (0, -1, 731, "90", None):
        with pytest.raises(ValueError):
            rot.lifetime_string(bad)


def test_the_expiry_date_is_read_from_databricks_timestamps():
    assert rot.parse_expire_time("2027-01-17T09:12:03.123Z") == dt.date(2027, 1, 17)


def test_the_github_secret_is_a_sealed_box_only_the_repository_key_can_open():
    from nacl.public import PrivateKey, SealedBox
    sk = PrivateKey.generate()
    pub = base64.b64encode(bytes(sk.public_key)).decode()
    enc = rot.encrypt_for_github(pub, NEW_SECRET)
    assert NEW_SECRET not in enc
    assert SealedBox(sk).decrypt(base64.b64decode(enc)).decode() == NEW_SECRET
    assert rot.encrypt_for_github(pub, NEW_SECRET) != enc            # a fresh ephemeral key every time


def test_the_expiry_entry_match_uses_whole_hyphen_words():
    assert rot.match_expiry_entry(ENTRIES, "packsense-deployer") == "packsense-deployer oauth secret"
    assert rot.match_expiry_entry(ENTRIES, "packsense-deployer-dev") == "packsense-deployer-dev oauth secret"
    assert rot.match_expiry_entry(ENTRIES, "packsense-gold") == "packsense-gold oauth secret"
    assert rot.match_expiry_entry(ENTRIES, "packsense-gold-dev") == "packsense-gold-dev oauth secret"


def test_no_match_or_two_matches_is_an_error_and_an_override_fixes_it():
    with pytest.raises(ValueError, match="0 entries"):
        rot.match_expiry_entry([{"name": "GH_TF_TOKEN", "expires": None}], "packsense-gold")
    twice = ENTRIES + [{"name": "packsense-gold backup", "expires": None}]
    with pytest.raises(ValueError, match="2 entries"):
        rot.match_expiry_entry(twice, "packsense-gold")
    assert rot.match_expiry_entry(twice, "packsense-gold", "packsense-gold backup") == "packsense-gold backup"
    with pytest.raises(ValueError):
        rot.match_expiry_entry(ENTRIES, "packsense-gold", "no such entry")


def test_updating_the_expiry_list_changes_one_entry_and_keeps_the_rest():
    new = json.loads(rot.update_expiry_list(json.dumps(ENTRIES), "packsense-gold-dev oauth secret", dt.date(2027, 1, 17)))
    assert [e["name"] for e in new] == [e["name"] for e in ENTRIES]
    assert new[3] == {"name": "packsense-gold-dev oauth secret", "expires": "2027-01-17", "note": "kept"}
    assert new[0] == ENTRIES[0] and new[4] == ENTRIES[4]
    assert json.loads(rot.update_expiry_list(json.dumps(ENTRIES), "GH_TF_TOKEN", None))[0]["expires"] is None
    with pytest.raises(ValueError):
        rot.update_expiry_list(json.dumps(ENTRIES), "nope", None)


def test_the_four_principals_are_distinct_dev_first_and_only_gold_has_a_scope():
    assert list(rot.PRINCIPALS)[:2] == ["packsense-deployer-dev", "packsense-gold-dev"]
    cfgs = rot.PRINCIPALS.values()
    assert len({c["client_id"] for c in cfgs}) == 4 and len({c["github_env"] for c in cfgs}) == 4
    assert {c["scope"] for c in cfgs if c["scope"]} == {"packsense_gold", "packsense_gold_dev"} and sum(1 for c in cfgs if c["scope"]) == 2


# ---- the order of the steps ---------------------------------------------------------------------------------------------------

def test_a_gold_rotation_runs_in_order_and_deletes_the_old_secrets_last():
    res, out, dbx, gh = run("packsense-gold")
    assert not isinstance(res, Exception), res
    kinds = [c[0] for c in dbx.log]
    assert kinds == ["create", "verify", "scope", "github", "expiry", "delete", "delete"]
    assert ("verify", True) in dbx.log and ("github", "prod-gold", "DATABRICKS_CLIENT_SECRET", True) in dbx.log
    assert ("create", "7776000s") in dbx.log
    assert json.loads(gh.value)[4]["expires"] == "2027-01-17"
    assert res["deleted"] == ["old0", "old1"]


def test_a_deployer_rotation_has_no_scope_step():
    res, out, dbx, gh = run("packsense-deployer-dev")
    assert [c[0] for c in dbx.log] == ["create", "verify", "github", "expiry", "delete", "delete"]


def test_keep_old_leaves_the_old_secrets_alone():
    res, out, dbx, gh = run("packsense-gold", keep_old=True)
    assert dbx.deleted == [] and res["deleted"] == []


def test_a_secret_that_does_not_sign_in_is_stored_nowhere_and_nothing_is_deleted():
    dbx = FakeDbx(verify_ok=False)
    res, out, dbx, gh = run("packsense-gold", dbx=dbx)
    assert isinstance(res, RuntimeError)
    kinds = [c[0] for c in dbx.log]
    assert "scope" not in kinds and "github" not in kinds and "delete" not in kinds and "expiry" not in kinds
    assert kinds.count("verify") == 6                                   # retried while the new secret becomes valid


def test_a_github_failure_keeps_every_old_secret_and_leaves_the_expiry_list_alone():
    log = []
    res, out, dbx, gh = run("packsense-gold", dbx=FakeDbx(log=log), gh=FakeGh(log, fail_put=True))
    assert isinstance(res, RuntimeError)
    assert dbx.deleted == [] and ("expiry",) not in log


def test_a_github_secret_whose_updated_at_did_not_move_is_a_failure_before_any_delete():
    log = []
    res, out, dbx, gh = run("packsense-gold", dbx=FakeDbx(log=log), gh=FakeGh(log, same_updated_at=True))
    assert isinstance(res, RuntimeError) and "updated_at" in str(res)
    assert dbx.deleted == [] and ("expiry",) not in log


def test_nothing_is_created_when_the_expiry_entry_cannot_be_found_or_the_principal_is_full():
    log = []
    res, out, dbx, gh = run("packsense-gold", dbx=FakeDbx(log=log), gh=FakeGh(log, entries=[{"name": "GH_TF_TOKEN", "expires": None}]))
    assert isinstance(res, ValueError) and ("create", "7776000s") not in log
    log2 = []
    res, out, dbx, gh = run("packsense-gold", dbx=FakeDbx(existing=4, log=log2))
    assert isinstance(res, RuntimeError) and not log2


def test_no_output_line_ever_contains_the_secret_value():
    res, out, dbx, gh = run("packsense-gold")
    assert out and all(NEW_SECRET not in line for line in out)
    res, out, dbx, gh = run("packsense-gold", dbx=FakeDbx(verify_ok=False))
    assert NEW_SECRET not in str(res) and all(NEW_SECRET not in line for line in out)


def test_a_github_error_names_the_request_and_status_but_never_the_token_or_body(monkeypatch):
    def boom(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 403, "no", {}, io.BytesIO(b'{"message":"token ghp_SECRETTOKEN is bad"}'))
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(RuntimeError) as e:
        rot.GitHub("ghp_SECRETTOKEN").variable()
    assert "ghp_SECRETTOKEN" not in str(e.value) and "HTTP 403" in str(e.value)
