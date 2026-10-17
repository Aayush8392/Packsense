import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold_lib import dbt_run  # noqa: E402


def test_build_args_pass_the_schema_target_and_private_paths():
    args = dbt_run.build_args("/tmp/p", "prod", "packsense_silver", "/tmp/t", "/tmp/l")
    assert args[0] == "build"
    assert args[args.index("--target") + 1] == "prod"
    assert json.loads(args[args.index("--vars") + 1]) == {"silver_schema": "packsense_silver"}
    assert args[args.index("--target-path") + 1] == "/tmp/t"
    assert args[args.index("--log-path") + 1] == "/tmp/l"
    assert args[args.index("--project-dir") + 1] == args[args.index("--profiles-dir") + 1] == "/tmp/p"


def test_only_dev_and_prod_are_valid_targets():
    assert dbt_run.check_target("dev") == "dev" and dbt_run.check_target("prod") == "prod"
    for bad in ("", "dev_admin", "PROD", "staging"):
        with pytest.raises(ValueError):
            dbt_run.check_target(bad)
    with pytest.raises(ValueError):
        dbt_run.build_args("/p", "dev_admin", "s", "/t", "/l")


def test_summary_is_ok_only_when_every_node_succeeded_or_passed():
    ok = dbt_run.summarise([("a", "success"), ("t1", "pass"), ("b", "success")])
    assert ok["ok"] and ok["total"] == 3 and ok["counts"] == {"success": 2, "pass": 1} and ok["bad"] == []
    bad = dbt_run.summarise([("a", "success"), ("t1", "fail"), ("b", "skipped")])
    assert not bad["ok"] and bad["bad"] == ["b=skipped", "t1=fail"]


def test_an_empty_result_is_never_ok():
    assert dbt_run.summarise([])["ok"] is False


def test_text_names_the_failures_and_counts():
    text = dbt_run.result_text(dbt_run.summarise([("a", "success"), ("t1", "fail")]))
    assert "2 nodes" in text and "fail 1" in text and "success 1" in text and "t1=fail" in text
    assert dbt_run.result_text(dbt_run.summarise([])) == "dbt build: 0 nodes (nothing ran)"


def test_freshness_text():
    assert dbt_run.freshness_text(0, None, None) == "silver manifest is empty"
    text = dbt_run.freshness_text(29, "2026-10-17 02:40", "openfoodfacts_products_1_2.json.gz")
    assert "29 files" in text and "openfoodfacts_products_1_2.json.gz" in text
