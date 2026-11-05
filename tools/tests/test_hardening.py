"""Item 7 hardening: hash-locked Python installs, committed Terraform lock files, and the required checks. No network."""
import base64
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import locks  # noqa: E402
import tf_lock  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"


# --- Python locks ---------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("lock", sorted(locks.LOCKS))
def test_every_package_in_a_lock_is_pinned_and_hashed(lock):
    text = (ROOT / lock).read_text(encoding="utf-8")
    entries = re.split(r"\n(?=[A-Za-z0-9_.-]+==)", text.strip())
    assert entries and all(re.match(r"^[A-Za-z0-9_.-]+==[^\s]+", e) for e in entries)
    for e in entries:
        assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", e)) >= 1, e.splitlines()[0]


@pytest.mark.parametrize("lock,inputs", sorted(locks.LOCKS.items()))
def test_every_directly_pinned_input_is_in_its_lock_at_that_version(lock, inputs):
    lock_text = (ROOT / lock).read_text(encoding="utf-8").lower()
    for rel in inputs:
        for line in (ROOT / rel).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+)==([^\s#]+)", line.strip())
            if m:
                assert f"{m.group(1).lower().replace('_', '-')}=={m.group(2).lower()}" in lock_text.replace("_", "-"), (rel, line)


def test_no_workflow_installs_from_an_unhashed_requirements_file():
    for wf in WORKFLOWS.glob("*.yml"):
        for n, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            if "pip install" in line:
                assert "--require-hashes" in line and ".lock" in line, f"{wf.name}:{n}: {line.strip()}"


def test_the_audit_covers_every_lock_and_the_ci_checks_that_locks_are_fresh():
    sec = (WORKFLOWS / "security.yml").read_text(encoding="utf-8")
    for lock in ("requirements-dev.lock", "p1_intake/requirements.lock", "p4_modelling/requirements.lock"):
        assert lock in sec
    assert "python tools/locks.py check" in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_the_cutoff_overrides_name_only_packages_pinned_on_purpose_or_fixed_for_an_advisory():
    pins = (ROOT / "requirements-dev.txt").read_text(encoding="utf-8")
    for pkg in locks.NEWER_OK:
        assert f"{pkg}==" in pins or re.fullmatch(r"PYSEC-\d{4}-\d+|GHSA-[\w-]+", locks.SECURITY_FIX.get(pkg, "")), pkg


# --- Terraform locks ------------------------------------------------------------------------------------------------------------------------------

def make_zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_h1_is_terraforms_dirhash_of_the_zip_files_in_name_order():
    files = {"terraform-provider-x_v1.0.0": b"binary", "LICENSE": b"text"}
    summary = "".join(f"{hashlib.sha256(files[n]).hexdigest()}  {n}\n" for n in ("LICENSE", "terraform-provider-x_v1.0.0"))
    expected = "h1:" + base64.b64encode(hashlib.sha256(summary.encode()).digest()).decode()
    assert tf_lock.h1_of_zip(make_zip(files)) == expected
    assert tf_lock.h1_of_zip(make_zip(dict(reversed(list(files.items()))))) == expected          # the order in the zip does not matter


@pytest.mark.parametrize("constraint,versions,expected", [
    ("~> 0.14", ["0.13.9", "0.14.0", "0.14.7", "0.15.1", "1.0.0", "0.16.0-beta1"], "0.15.1"),
    ("~> 6.13", ["6.12.0", "6.13.0", "6.13.2", "7.0.0"], "6.13.2"),
    ("~> 6.13.1", ["6.13.0", "6.13.1", "6.13.4", "6.14.0"], "6.13.4"),
])
def test_the_newest_version_inside_the_constraint_is_chosen(constraint, versions, expected):
    assert tf_lock.newest_within(versions, constraint) == expected


@pytest.mark.parametrize("root", sorted(p.parent.name for p in (ROOT / "infra" / "terraform").glob("*/versions.tf")))
def test_each_terraform_root_has_a_committed_lock_that_covers_its_providers_and_every_platform(root):
    d = ROOT / "infra" / "terraform" / root
    lock = (d / ".terraform.lock.hcl").read_text(encoding="utf-8")
    for ns, typ, constraint in tf_lock.providers_of(d):
        m = re.search(rf'provider "registry.terraform.io/{ns.lower()}/{typ}" \{{\s*version\s*=\s*"([\d.]+)"\s*constraints\s*=\s*"{re.escape(constraint)}"', lock)
        assert m, (root, ns, typ)
        block = lock[m.start():lock.index("\n}", m.start())]
        assert len(re.findall(r'"h1:', block)) == len(tf_lock.PLATFORMS) and len(re.findall(r'"zh:', block)) == len(tf_lock.PLATFORMS)


def test_every_terraform_init_refuses_to_change_the_lock():
    for wf in WORKFLOWS.glob("terraform-*.yml"):
        for line in wf.read_text(encoding="utf-8").splitlines():
            if "terraform init" in line:
                assert "-lockfile=readonly" in line, f"{wf.name}: {line.strip()}"


def test_the_lock_files_are_not_git_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".terraform.lock.hcl" not in ignore


# --- required checks ------------------------------------------------------------------------------------------------------------------------------

def test_the_ruleset_requires_tests_lint_and_engines_and_ci_has_those_jobs():
    tf = (ROOT / "infra" / "terraform" / "github" / "main.tf").read_text(encoding="utf-8")
    required = set(re.findall(r'required_check \{\s*context\s*=\s*"([^"]+)"', tf))
    assert required == {"tests", "lint", "engines"}
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for job in required:
        assert re.search(rf"^  {job}:", ci, re.M), job


def test_the_only_accepted_advisories_are_the_documented_oauthlib_ones_and_only_on_the_gold_lock():
    sec = (WORKFLOWS / "security.yml").read_text(encoding="utf-8")
    ignored = re.findall(r"--ignore-vuln (\S+)", sec)
    assert ignored == ["PYSEC-2026-4114", "CVE-2026-49272"]
    line = next(x for x in sec.splitlines() if "--ignore-vuln" in x)
    assert "p4_modelling/requirements.lock" in line
    locks = (ROOT / "tools" / "locks.py").read_text(encoding="utf-8")
    assert "PYSEC-2026-4114" in locks and "CVE-2026-49272" in locks


# --- the weekly cutoff bump (lock-refresh workflow) -----------------------------------------------------------------------------------------------

def test_bump_cutoff_moves_to_fourteen_days_before_today_and_touches_nothing_else():
    import datetime as dt
    text = 'A = 1\nCUTOFF = "2026-10-07T00:00:00Z"\nSECURITY_FIX = {"x": "y"}\n'
    out = locks.bump_cutoff(text, dt.date(2026, 11, 9))
    assert out == 'A = 1\nCUTOFF = "2026-10-26T00:00:00Z"\nSECURITY_FIX = {"x": "y"}\n'


def test_bump_cutoff_never_moves_backwards():
    import datetime as dt
    text = 'CUTOFF = "2026-10-26T00:00:00Z"\n'
    assert locks.bump_cutoff(text, dt.date(2026, 10, 20)) == text
    assert locks.bump_cutoff(text, dt.date(2026, 11, 9)) == text


def test_bump_cutoff_needs_a_cutoff_line():
    import datetime as dt
    with pytest.raises(ValueError):
        locks.bump_cutoff("A = 1\n", dt.date(2026, 11, 9))


def test_the_real_locks_file_has_exactly_one_cutoff_line():
    assert len(locks.CUTOFF_LINE.findall((ROOT / "tools" / "locks.py").read_text(encoding="utf-8"))) == 1


def test_production_locks_use_the_frozen_cutoff_and_the_rest_use_the_moving_one():
    assert locks.PRODUCTION_LOCKS <= set(locks.LOCKS)
    assert {locks.cutoff_for(lock) for lock in locks.PRODUCTION_LOCKS} == {locks.PRODUCTION_CUTOFF}
    tooling = set(locks.LOCKS) - locks.PRODUCTION_LOCKS
    assert tooling == {"requirements-dev.lock", ".github/requirements/zizmor.lock", ".github/requirements/pip-audit.lock", ".github/requirements/uv-tool.lock"}
    assert {locks.cutoff_for(lock) for lock in tooling} == {locks.CUTOFF}


def test_the_refresh_workflow_never_stages_a_production_lock_and_guards_against_one_moving():
    text = (WORKFLOWS / "lock-refresh.yml").read_text(encoding="utf-8")
    add_line = next(line for line in text.splitlines() if line.strip().startswith("git add "))
    assert "p1_intake" not in add_line and "p4_modelling" not in add_line
    assert "git diff --quiet -- p1_intake/requirements.lock p4_modelling/requirements.lock" in text


def test_dependabot_opens_no_version_update_pull_requests():
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert text.count("package-ecosystem:") == text.count("open-pull-requests-limit: 0")


def test_the_refresh_workflow_opens_no_pull_request_and_moves_main_only_after_the_three_required_checks():
    text = (WORKFLOWS / "lock-refresh.yml").read_text(encoding="utf-8")
    assert "gh pr " not in text                                    # a bot's pull request would wait for a person to approve its runs
    ci = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    for job in ("tests", "lint", "engines"):                         # the three contexts of the `require-ci` ruleset exist as CI jobs and are waited for by name
        assert re.search(rf"^  {job}:", ci, re.MULTILINE), job
        assert f'.name=="{job}"' in text, job
    assert text.index('RESULT="green"') < text.index(":refs/heads/main")   # main is pushed after the wait, never before
    assert "--force" not in text.split(":refs/heads/main")[0].splitlines()[-1]   # the move of main is never forced
