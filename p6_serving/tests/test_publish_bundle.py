"""The publish bundle's wiring and the setup script's marker patch: the job runs as the dedicated principal, reads only the spec's tables, and holds no secret."""
import re
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p6_serving"))
import export_lib as ex  # noqa: E402
import setup_publish as sp  # noqa: E402

BUNDLE = yaml.safe_load((ROOT / "p6_serving" / "databricks.yml").read_text(encoding="utf-8"))
JOB = yaml.safe_load((ROOT / "p6_serving" / "resources" / "publish_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["publish_site_data"]
GRANTS = yaml.safe_load((ROOT / "p5_governance" / "grants.yml").read_text(encoding="utf-8"))
NOTEBOOK = ROOT / "p6_serving" / "notebooks" / "publish_site_data.py"


def test_the_job_runs_as_the_publish_principal_and_that_principal_may_read_its_notebook():
    run_as = JOB["run_as"]["service_principal_name"]
    assert [p["service_principal_name"] for p in BUNDLE["permissions"]] == [run_as]


def test_the_notebook_exists_and_is_not_retried():
    task = JOB["tasks"][0]
    assert (ROOT / "p6_serving" / "resources" / task["notebook_task"]["notebook_path"]).resolve() == NOTEBOOK.resolve()
    assert task["disable_auto_optimization"] is True


def test_no_parameter_carries_a_secret():
    params = JOB["tasks"][0]["notebook_task"]["base_parameters"]
    assert not [k for k in params if re.search(r"token|secret|key|password", k, re.I)]
    assert "dbutils.secrets.get(SCOPE, \"hf_site_token\")" in NOTEBOOK.read_text(encoding="utf-8")   # the token is read from the scope, never passed in


def test_the_job_is_scheduled_after_the_gold_build():
    assert BUNDLE["variables"]["publish_pause"]["default"] in ("PAUSED", "UNPAUSED")
    sec, minute, hour = BUNDLE["variables"]["publish_cron"]["default"].split()[:3]
    assert int(hour) * 60 + int(minute) >= 8 * 60 + 45        # the gold build starts 08:15 UTC and takes about 4 minutes


def test_the_principal_reads_exactly_the_spec_tables_and_one_scope():
    spec = ex.load_spec()
    wanted = {f"{d.get('schema') or 'workspace.packsense_gold'}.{d['table']}" for d in spec["datasets"].values()}
    got = {s["name"] for s in GRANTS["securables"] if s["type"] == "table" and "packsense-publish" in s["grants"]}
    assert got == wanted
    others = [s["name"] for s in GRANTS["securables"] if s["type"] != "table" and "packsense-publish" in s["grants"]]
    assert sorted(others) == ["workspace", "workspace.packsense_gold", "workspace.packsense_health"]
    for s in GRANTS["securables"]:
        if "packsense-publish" in s["grants"]:
            assert set(s["grants"]["packsense-publish"]) <= {"USE_CATALOG", "USE_SCHEMA", "SELECT"}
    assert GRANTS["secret_scopes"]["packsense_publish"] == {"packsense-publish": "READ", "admin": "MANAGE"}


def test_the_notebook_reads_only_through_the_specs_select():
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert "ex.select_sql(" in text and "product_history" not in text
    assert "spark.sql(" in text and text.count("spark.sql(") == 1


def test_the_marker_patch_replaces_every_marker_and_refuses_a_bad_id():
    good = "12345678-1234-1234-1234-123456789abc"
    assert sp.patch_marker(f"a {sp.MARKER} b {sp.MARKER}", good) == f"a {good} b {good}"
    with pytest.raises(ValueError):
        sp.patch_marker(sp.MARKER, "not-a-uuid")


def test_every_marker_file_exists():
    for rel in sp.MARKER_FILES:
        assert (ROOT / rel).is_file(), rel


def test_the_bundle_ships_every_folder_the_notebook_imports_from():
    """Found 2026-10-21: the first run failed because classification_lib imports from p9_operations, which the bundle did not ship."""
    synced = {Path(p).name for p in BUNDLE["sync"]["paths"]}
    files = [ROOT / "p6_serving" / "export_lib.py", ROOT / "p5_governance" / "licence_gate.py", ROOT / "p5_governance" / "classification_lib.py"]
    needed = set()
    for f in files:
        needed |= set(re.findall(r'"(p\d_[a-z_]+)"', f.read_text(encoding="utf-8")))
    assert needed <= synced, f"not shipped: {sorted(needed - synced)}"
