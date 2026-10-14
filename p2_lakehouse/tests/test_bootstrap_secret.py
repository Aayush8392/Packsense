"""The secret-handling bootstrap: name validation and the guards that run before anything touches Databricks."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bootstrap"))

import create_hmac_key as bootstrap  # noqa: E402


def test_plain_names_are_accepted():
    for name in ("healthchecks_core_ping_url", "hf.token", "a-b_c.1"):
        assert bootstrap.check_secret_name(name) == name


@pytest.mark.parametrize("name", ["", "has space", "../x", "a/b", "x" * 129, "naïve"])
def test_odd_names_are_rejected(name):
    with pytest.raises(SystemExit):
        bootstrap.check_secret_name(name)


@pytest.mark.parametrize("name", ["hmac_key_v1", "hmac_key_v2", "hmac_key"])
def test_the_hmac_key_can_never_be_written_by_put_secret(name):
    with pytest.raises(SystemExit, match="HMAC"):
        bootstrap.check_secret_name(name)


def test_put_secret_without_a_name_stops_before_any_connection(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["create_hmac_key.py", "put-secret"])
    for var in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit, match="--name"):
        bootstrap.main()


def test_a_bad_name_is_refused_before_connecting_or_prompting(monkeypatch):
    called = []
    monkeypatch.setattr(bootstrap.getpass, "getpass", lambda *a, **k: called.append("prompted") or "value")
    for var in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(SystemExit):
        bootstrap.cmd_put_secret("hmac_key_v1", replace=True)
    assert called == []


def test_dry_run_needs_no_credentials(monkeypatch, capsys):
    for var in ("DATABRICKS_HOST", "DATABRICKS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert bootstrap.cmd_dry_run() == 0
    out = capsys.readouterr().out
    assert "nothing stored" in out and "64-character" in out


def test_key_check_value_is_eight_hex_characters_and_not_the_key():
    key = "ab" * 32
    check = bootstrap.key_check(key)
    assert len(check) == 8 and int(check, 16) >= 0 and check not in key
