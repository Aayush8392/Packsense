import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("gold_scope", Path(__file__).resolve().parents[1] / "bootstrap" / "gold_scope.py")
gold_scope = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gold_scope)


def test_only_the_two_gold_scopes_are_allowed_never_the_real_one():
    assert gold_scope.check_scope("packsense_gold") == "packsense_gold"
    assert gold_scope.check_scope("packsense_gold_dev") == "packsense_gold_dev"
    for bad in ("packsense", "packsense_dev", "", "packsense_gold2"):
        with pytest.raises(SystemExit):
            gold_scope.check_scope(bad)


def test_only_the_three_known_secret_names_are_allowed():
    for name in ("oauth_client_id", "oauth_client_secret", "healthchecks_gold_ping_url"):
        assert gold_scope.check_secret_name(name) == name
    for bad in ("hmac_key_v1", "hf_archive_token", "", "oauth"):
        with pytest.raises(SystemExit):
            gold_scope.check_secret_name(bad)


def test_the_principal_must_be_a_client_id_uuid():
    assert gold_scope.check_principal("05620ebf-cd4d-4b0a-88ad-029915441965")
    for bad in ("", "mr.aayush89@gmail.com", "05620ebf", "05620EBF-CD4D-4B0A-88AD-029915441965"):
        with pytest.raises(SystemExit):
            gold_scope.check_principal(bad)
