"""Hash-locked Python dependencies: one lock file per requirements input, all made the same way.

  python tools/locks.py compile    rewrite every lock file (needs `uv`; `pip install -r .github/requirements/uv-tool.lock` gives the pinned one)
  python tools/locks.py bump       move CUTOFF (the three scanner and tool locks only) to 14 days before today (the weekly `lock-refresh` workflow runs this, then `compile`)
  python tools/locks.py check      recompile into a temporary folder and exit 1 if any committed lock differs (CI runs this in the `lint` job)

The inputs (`requirements*.txt`) are what a person edits; the locks (`*.lock`) pin every package, transitive ones included, with the hashes of its files, and every
workflow installs with `pip install --require-hashes -r <lock>`. Two settings keep a lock reproducible: `--exclude-newer` (a package must be at least two weeks old on the
cutoff date; move the date forward in this file when you want newer versions, then `compile`) and `--universal` (one file that holds for Windows, Linux and macOS).
`--no-annotate` leaves out the "via" comments, whose paths differ between systems. A pin the person chose on purpose may be newer than the cutoff: list it in NEWER_OK.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-10-22T00:00:00Z"                   # the TOOLING locks: moved forward each week by the lock-refresh workflow (`bump`)
FROZEN_CUTOFF = "2026-10-07T00:00:00Z"            # the FROZEN locks (capture, gold build, and the dev lock that the Pages build installs next to a secret): never moved by a bot; a person moves it for a deliberate update
PYTHON = "3.12"                                   # the version the workflows run on
SECURITY_FIX = {                                  # packages locked newer than the cutoff because pip-audit found an advisory fixed after it (found 2026-10-21)
    "certifi": "PYSEC-2026-4320",                 # fixed in 2026.10.19
    "uv": "GHSA-hq85-5cpj-mr62",                 # 0.13.4 (2026-10-20): uv before it trusted an emSign root with compromised intermediate keys
    "pyasn1": "GHSA-2qm8-x737-gmw5",             # 0.6.5 (2026-10-27): four quadratic-time denial-of-service flaws in its decoders (this id, GHSA-9m75-vc3g-4x39, GHSA-fm9c-5rcf-2q5p,
                                                 # GHSA-mm57-4v3p-rchx; CVE-2026-119194 to -119197), found 2026-11-04; reached only through other libraries, we decode no untrusted ASN.1
}
SECURITY_FIX_FROM = {"pyasn1": "2026-10-28T00:00:00Z"}   # the release date of the fix, rounded up; the date used for the others is the day the first exceptions were found
NEWER_OK = {"databricks-sdk": "2026-10-21T00:00:00Z", **{pkg: SECURITY_FIX_FROM.get(pkg, "2026-10-21T00:00:00Z") for pkg in SECURITY_FIX}}   # databricks-sdk: pinned on purpose before it was two weeks old
# Not fixable here, so accepted in .github/workflows/security.yml (`--ignore-vuln`, p4 lock only): PYSEC-2026-4114, oauthlib 3.3.1 (fixed in 4.0.0). dbt-databricks 1.12.6 caps
# databricks-sql-connector at 4.4.0, which needs oauthlib < 4. It is a timing flaw in the server-side PKCE check of an OAuth provider; we run client flows only.
# Also accepted: CVE-2026-49272 (GHSA-3jp2-3mrg-2vxc, published 2026-10-27, same package and same fix version): the device-code token endpoint of an OAuth provider does not check
# the device code. Again server-side code that we do not run.
# Revisit when dbt-databricks moves to a connector that allows oauthlib 4.

LOCKS = {                                         # lock file -> its input files
    "requirements-dev.lock": ["requirements-dev.txt"],
    "p1_intake/requirements.lock": ["p1_intake/requirements.txt"],
    "p4_modelling/requirements.lock": ["p4_modelling/requirements.txt", "p4_modelling/requirements-duckdb.txt"],
    "p8_steward/nightly/requirements.lock": ["p8_steward/nightly/requirements.txt"],
    ".github/requirements/zizmor.lock": [".github/requirements/zizmor.txt"],
    ".github/requirements/pip-audit.lock": [".github/requirements/pip-audit.txt"],
    ".github/requirements/uv-tool.lock": [".github/requirements/uv-tool.txt"],
}


FROZEN_LOCKS = {"p1_intake/requirements.lock", "p4_modelling/requirements.lock", "requirements-dev.lock", "p8_steward/nightly/requirements.lock"}   # production code (the nightly job holds the Gemini key and a write token), plus the dev lock that pages.yml installs while it holds a secret
# every other lock (zizmor, pip-audit, uv-tool) is used only by workflows that hold no secret, and is moved by the weekly lock-refresh workflow


def cutoff_for(lock: str) -> str:
    return FROZEN_CUTOFF if lock in FROZEN_LOCKS else CUTOFF


# Per-lock exceptions (the global NEWER_OK would also move the other locks that contain the package). The nightly job decodes photos uploaded to Open Food Facts by anyone and holds the
# Gemini key and a write token, and pip-audit found advisories on the versions the frozen cutoff allows (2026-11-13): Pillow 12.3.0 (42 advisories, fixed in 13.0.0, released 2026-10-16)
# and filelock 4.0.12 (13 advisories, fixed in 4.2.1, released 2026-10-17). Each date is the fix's release day rounded up.
LOCK_NEWER_OK = {"p8_steward/nightly/requirements.lock": {"pillow": "2026-10-17T00:00:00Z", "filelock": "2026-10-18T00:00:00Z"}}


def compile_one(inputs: list[str], out: Path, cutoff: str = CUTOFF, newer_ok: dict | None = None) -> None:
    out.unlink(missing_ok=True)                   # uv prefers the versions in an existing output file; a lock is always resolved from scratch, as `check` does
    newer = {**NEWER_OK, **(newer_ok or {})}
    cmd = ["uv", "pip", "compile", "--generate-hashes", "--universal", "--no-header", "--no-annotate", "--quiet", "--python-version", PYTHON,
           "--exclude-newer", cutoff, *[a for pkg, d in newer.items() for a in ("--exclude-newer-package", f"{pkg}={d}")],
           *inputs, "-o", str(out)]
    subprocess.run(cmd, cwd=ROOT, check=True)


CUTOFF_LINE = re.compile(r'^CUTOFF = "[0-9T:Z-]+"', re.MULTILINE)
CUTOFF_AGE_DAYS = 14                              # a package must be at least this old on the cutoff date


def bump_cutoff(text: str, today: dt.date, age_days: int = CUTOFF_AGE_DAYS) -> str:
    """The text of this file with `CUTOFF` moved to `age_days` before `today` (midnight UTC). The other settings (SECURITY_FIX, NEWER_OK) are left alone.
    A cutoff is never moved backwards: a date older than the current one leaves the text as it is."""
    new = dt.datetime.combine(today - dt.timedelta(days=age_days), dt.time(), tzinfo=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    current = CUTOFF_LINE.search(text)
    if not current:
        raise ValueError("no CUTOFF line found")
    if current.group(0).split('"')[1] >= new:
        return text
    return CUTOFF_LINE.sub(f'CUTOFF = "{new}"', text, count=1)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in ("compile", "check", "bump"):
        print(__doc__)
        return 2
    if argv[1] == "bump":
        path = Path(__file__).resolve()
        old = path.read_text(encoding="utf-8")
        new = bump_cutoff(old, dt.datetime.now(dt.timezone.utc).date())
        path.write_text(new, encoding="utf-8", newline="")
        print("cutoff moved" if new != old else "cutoff already current")
        return 0
    if argv[1] == "compile":
        for lock, inputs in LOCKS.items():
            compile_one(inputs, ROOT / lock, cutoff_for(lock), LOCK_NEWER_OK.get(lock))
            print("wrote", lock)
        return 0
    tmp = Path(tempfile.mkdtemp())
    try:
        stale = []
        for lock, inputs in LOCKS.items():
            out = tmp / lock.replace("/", "_")
            compile_one(inputs, out, cutoff_for(lock), LOCK_NEWER_OK.get(lock))
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
