"""One-off: the canary's SAVED INPUTS (decided 2026-11-18; the canary failed on 17 and 18 Nov and a fetch problem could not be told from a wrong reading).

  python p8_steward/nightly/make_canary_inputs.py [--env-file .env] [--force]

Reads output/nightly_inputs/canary.json (the ten judged-right canary products, written once by make_stage_inputs.py), fetches each product's scan text and photo ONCE from Open Food Facts
with the night's own fetch, reads each through the night's own pipeline with the real model readers, and writes output/nightly_inputs/canary_fixed.json ONLY IF EVERY product agrees with its
saved right table. Otherwise it writes nothing, says which products did not agree and why (counts and codes: local output only), and exits 1.

canary_fixed.json = canary.json plus, per row, "ocr_text" (the scan text) and "photo_b64" (the resized photo, base64). It is gitignored (the photos are other people's images; the repository is
public) and is uploaded BY HAND to the private results datasets as input/canary.json: the scratch dataset first, then the real one. Needs GEMINI_API_KEY in the environment or the env file.
Cost: at most about 4 model requests per product (2 normally), capped at 60 in all.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
from nightly import budget as bd  # noqa: E402
from nightly import night as nt  # noqa: E402

SRC = ROOT / "output" / "nightly_inputs" / "canary.json"
OUT = ROOT / "output" / "nightly_inputs" / "canary_fixed.json"
MAX_CALLS = 60


def _env(path: Path | None) -> dict:
    env = dict(os.environ)
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


def build(rows: list[dict], readers, budget, night: str) -> tuple[list[dict], dict]:
    """(rows with saved inputs, {code: why}) for the products that did NOT agree. Pure given the readers: fetch each row ONCE, then read the saved inputs through run_canary."""
    fixed, problems = [], {}
    for row in rows:
        try:
            got = readers.fetch(row["code"])
        except Exception as e:                                         # noqa: BLE001  (any failure: say which product and stop trusting it)
            problems[row["code"]] = f"fetch:{type(e).__name__}"
            continue
        if not (got.get("has_photo") and got.get("ocr_text") and got.get("photo")):
            problems[row["code"]] = "fetch:no photo or no scan text"
            continue
        fixed.append({**row, "ocr_text": got["ocr_text"], "photo_b64": base64.b64encode(got["photo"]).decode("ascii")})
    if problems:
        return [], problems
    checked = nt.run_canary([{**r, "photo": base64.b64decode(r["photo_b64"])} for r in fixed], readers, budget, night, max_miss=0)
    if checked["missed"]:
        return [], dict(checked["missed_detail"])
    return fixed, {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", type=Path, default=ROOT / ".env")
    ap.add_argument("--night", default=None, help="a date label, default today (UTC)")
    ap.add_argument("--force", action="store_true", help="overwrite an existing canary_fixed.json")
    a = ap.parse_args(argv)
    if OUT.exists() and not a.force:
        print(f"{OUT.name} exists; use --force to rebuild it")
        return 2
    import datetime as dt
    night = a.night or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    env = _env(a.env_file)
    from nightly import readers as rdrs
    rows = json.loads(SRC.read_text(encoding="utf-8"))["canary"]
    fixed, problems = build(rows, rdrs.make_readers(env, need_model=True), bd.Budget(max_calls=MAX_CALLS), night)
    if problems:
        print(f"NOT WRITTEN: {len(problems)} of {len(rows)} canary products did not pass:")
        for code, why in sorted(problems.items()):
            print(f"  {code}: {why}")
        return 1
    OUT.write_text(json.dumps({"canary": fixed}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {OUT.name}: {len(fixed)} products, all {len(fixed)} agree with their saved right tables; {OUT.stat().st_size / 1e6:.1f} MB; upload it by hand as input/canary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
