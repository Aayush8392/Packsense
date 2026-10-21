"""Hash-locked Python dependencies: one lock file per requirements input, all made the same way.

  python tools/locks.py compile    rewrite every lock file (needs `uv`; `pip install -r .github/requirements/uv-tool.lock` gives the pinned one)
  python tools/locks.py check      recompile into a temporary folder and exit 1 if any committed lock differs (CI runs this in the `lint` job)

The inputs (`requirements*.txt`) are what a person edits; the locks (`*.lock`) pin every package, transitive ones included, with the hashes of its files, and every
workflow installs with `pip install --require-hashes -r <lock>`. Two settings keep a lock reproducible: `--exclude-newer` (a package must be at least two weeks old on the
cutoff date; move the date forward in this file when you want newer versions, then `compile`) and `--universal` (one file that holds for Windows, Linux and macOS).
`--no-annotate` leaves out the "via" comments, whose paths differ between systems. A pin the person chose on purpose may be newer than the cutoff: list it in NEWER_OK.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-10-07T00:00:00Z"
PYTHON = "3.12"                                   # the version the workflows run on
SECURITY_FIX = {                                  # packages locked newer than the cutoff because pip-audit found an advisory fixed after it (found 2026-10-21)
    "certifi": "PYSEC-2026-4320",                 # fixed in 2026.10.19
    "uv": "GHSA (Dependabot alert 4, critical)",  # 0.13.4 (2026-10-20): uv before it trusted an emSign root with compromised intermediate keys
}
NEWER_OK = {"databricks-sdk": "2026-10-21T00:00:00Z", **{pkg: "2026-10-21T00:00:00Z" for pkg in SECURITY_FIX}}   # databricks-sdk: pinned on purpose before it was two weeks old
# Not fixable here, so accepted in .github/workflows/security.yml (`--ignore-vuln`, p4 lock only): PYSEC-2026-4114, oauthlib 3.3.1 (fixed in 4.0.0). dbt-databricks 1.12.6 caps
# databricks-sql-connector at 4.4.0, which needs oauthlib < 4. It is a timing flaw in the server-side PKCE check of an OAuth provider; we run client flows only.
# Revisit when dbt-databricks moves to a connector that allows oauthlib 4.

LOCKS = {                                         # lock file -> its input files
    "requirements-dev.lock": ["requirements-dev.txt"],
    "p1_intake/requirements.lock": ["p1_intake/requirements.txt"],
    "p4_modelling/requirements.lock": ["p4_modelling/requirements.txt", "p4_modelling/requirements-duckdb.txt"],
    ".github/requirements/zizmor.lock": [".github/requirements/zizmor.txt"],
    ".github/requirements/pip-audit.lock": [".github/requirements/pip-audit.txt"],
    ".github/requirements/uv-tool.lock": [".github/requirements/uv-tool.txt"],
}


def compile_one(inputs: list[str], out: Path) -> None:
    out.unlink(missing_ok=True)                   # uv prefers the versions in an existing output file; a lock is always resolved from scratch, as `check` does
    cmd = ["uv", "pip", "compile", "--generate-hashes", "--universal", "--no-header", "--no-annotate", "--quiet", "--python-version", PYTHON,
           "--exclude-newer", CUTOFF, *[a for pkg, d in NEWER_OK.items() for a in ("--exclude-newer-package", f"{pkg}={d}")],
           *inputs, "-o", str(out)]
    subprocess.run(cmd, cwd=ROOT, check=True)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("compile", "check"):
        print(__doc__)
        return 2
    if argv[1] == "compile":
        for lock, inputs in LOCKS.items():
            compile_one(inputs, ROOT / lock)
            print("wrote", lock)
        return 0
    tmp = Path(tempfile.mkdtemp())
    try:
        stale = []
        for lock, inputs in LOCKS.items():
            out = tmp / lock.replace("/", "_")
            compile_one(inputs, out)
            committed = (ROOT / lock).read_text(encoding="utf-8").replace("\r\n", "\n") if (ROOT / lock).exists() else None
            if committed != out.read_text(encoding="utf-8").replace("\r\n", "\n"):
                stale.append(lock)
        if stale:
            print("stale or missing lock files (run `python tools/locks.py compile` and commit):", ", ".join(stale))
            return 1
        print(f"all {len(LOCKS)} lock files match their inputs")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
