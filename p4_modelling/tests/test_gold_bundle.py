"""The gold bundle's settings are checked against each other and against the dbt requirements (no deployment needed)."""
import re
from pathlib import Path

import yaml

P4 = Path(__file__).resolve().parents[1]
BUNDLE = yaml.safe_load((P4 / "databricks.yml").read_text(encoding="utf-8"))
JOB = yaml.safe_load((P4 / "resources" / "gold_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["gold_build"]
REQUIREMENTS = [line.strip() for line in (P4 / "requirements.txt").read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")]


def test_the_job_environment_pins_exactly_the_requirements_file():
    spec = JOB["environments"][0]["spec"]
    assert sorted(spec["dependencies"]) == sorted(REQUIREMENTS)
    assert all("==" in d for d in spec["dependencies"])
    assert JOB["tasks"][0]["environment_key"] == JOB["environments"][0]["environment_key"]


def test_the_notebook_exists_and_the_schedule_comes_from_one_variable():
    task = JOB["tasks"][0]
    assert (P4 / "resources" / task["notebook_task"]["notebook_path"]).resolve().is_file()
    assert JOB["schedule"]["quartz_cron_expression"] == "${var.gold_cron}"
    assert "gold_cron" in BUNDLE["variables"]
    assert JOB["max_concurrent_runs"] == 1


def test_dev_and_prod_use_separate_schemas_scopes_and_targets():
    v = BUNDLE["variables"]
    prod = BUNDLE["targets"]["prod"]["variables"]
    assert v["dbt_target"]["default"] == "dev" and prod["dbt_target"] == "prod"
    assert v["silver_schema"]["default"] == "packsense_dev_silver" and prod["silver_schema"] == "packsense_silver"
    assert v["secret_scope"]["default"] == "packsense_gold_dev" and prod["secret_scope"] == "packsense_gold"
    assert v["ping"]["default"] == "false" and prod["ping"] == "true"
    assert BUNDLE["targets"]["dev"]["mode"] == "development"


def test_no_gold_target_can_reach_the_real_secret_scope_or_bronze():
    text = (P4 / "databricks.yml").read_text(encoding="utf-8") + (P4 / "resources" / "gold_job.yml").read_text(encoding="utf-8")
    assert not re.search(r"secret_scope:\s*packsense\s*$", text, re.M)
    assert "bronze" not in text.lower().replace("bronze principal", "").replace("never reads bronze", "")


def test_the_deployed_copy_keeps_the_dbt_tests_and_leaves_out_the_bootstrap_and_python_tests():
    excluded = BUNDLE["sync"]["exclude"]
    assert "**/tests/**" in excluded and "**/bootstrap/**" in excluded
    # `**/tests/**` must not swallow the dbt data tests (the build runs them)
    assert not re.fullmatch(r"tests", "data_tests")
    assert (P4 / "data_tests").is_dir()
