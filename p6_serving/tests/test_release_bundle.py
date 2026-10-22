"""The India release bundle's wiring: an admin-owned job (it needs plaintext contributor names that only bronze holds), paused until the first release is checked, no
secret in a parameter, every imported folder shipped, one scope readable by the admin only, and the notebook calls the exit function and the gate only through release_lib."""
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p6_serving"))
import release_lib as rl  # noqa: E402
import setup_release as sr  # noqa: E402

BUNDLE = yaml.safe_load((ROOT / "p6_serving" / "release" / "databricks.yml").read_text(encoding="utf-8"))
JOB = yaml.safe_load((ROOT / "p6_serving" / "release" / "resources" / "release_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["release_india"]
GRANTS = yaml.safe_load((ROOT / "p5_governance" / "grants.yml").read_text(encoding="utf-8"))
NOTEBOOK = ROOT / "p6_serving" / "notebooks" / "release_india.py"


def test_the_job_is_admin_owned_not_retried_and_starts_paused():
    assert "run_as" not in JOB and "permissions" not in BUNDLE
    task = JOB["tasks"][0]
    assert task["disable_auto_optimization"] is True
    assert (ROOT / "p6_serving" / "release" / "resources" / task["notebook_task"]["notebook_path"]).resolve() == NOTEBOOK.resolve()
    assert BUNDLE["variables"]["release_pause"]["default"] == "PAUSED"


def test_no_parameter_carries_a_secret_and_the_token_is_read_from_the_scope():
    params = JOB["tasks"][0]["notebook_task"]["base_parameters"]
    assert not [k for k in params if re.search(r"token|secret|key|password", k, re.I)]
    assert 'dbutils.secrets.get(SCOPE, "hf_release_token")' in NOTEBOOK.read_text(encoding="utf-8")


def test_the_bundle_ships_every_folder_the_release_imports_from():
    synced = {Path(p).name for p in BUNDLE["sync"]["paths"]}
    files = [ROOT / "p6_serving" / "release_lib.py", ROOT / "p6_serving" / "export_lib.py", ROOT / "p5_governance" / "licence_gate.py",
             ROOT / "p5_governance" / "classification_lib.py"]
    needed = set()
    for f in files:
        needed |= set(re.findall(r'"(p\d_[a-z_]+)"', f.read_text(encoding="utf-8")))
    assert needed <= synced, f"not shipped: {sorted(needed - synced)}"


def test_the_scope_is_listed_in_the_grants_file_for_the_admin_only():
    assert GRANTS["secret_scopes"][sr.SCOPE] == {"admin": "MANAGE"}
    assert sr.SCOPE == rl.load_spec()["release"]["secret_scope"]


def test_the_notebook_writes_nothing_before_the_build_and_never_prints_names():
    text = NOTEBOOK.read_text(encoding="utf-8")
    assert text.index("rl.build_release(") < text.index("create_commit(")
    assert "dry_run" in text and "if DRY:" in text
    import ast
    secret_names = {"handles", "raw_names", "own", "ordinary_extra", "wanted"}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "print":
            for arg in node.args:
                bare = [n for n in ast.walk(arg) if isinstance(n, ast.Name) and n.id in secret_names]
                inside_len = [n for c in ast.walk(arg) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "len" for n in ast.walk(c) if isinstance(n, ast.Name)]
                assert all(n in inside_len for n in bare), "the notebook prints a name collection, not only its size"


def test_the_schedule_is_monthly_and_after_the_daily_jobs():
    sec, minute, hour, dom = BUNDLE["variables"]["release_cron"]["default"].split()[:4]
    assert dom != "*" and int(hour) * 60 + int(minute) >= 10 * 60 + 30
