"""Adds a further part of the review set (fetched with fetch_review_set.py --name <name>) to the main review set in output/review_set/ (gitignored).

  python p8_steward/bootstrap/merge_review_part.py dev2
The new products' version rows are appended to stg_silver_versions.jsonl, their groups to manifest.json (cases_per_code), and their barcodes to split.json under the part's name.
It refuses to add a barcode that is already in the review set, so no product can be in two parts (and a test card can never become a development card this way).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SET = ROOT / "output" / "review_set"


def merge(name: str) -> dict:
    part = ROOT / "output" / f"review_set_{name}"
    manifest = json.loads((SET / "manifest.json").read_text(encoding="utf-8"))
    new = json.loads((part / "manifest.json").read_text(encoding="utf-8"))
    split = json.loads((SET / "split.json").read_text(encoding="utf-8"))
    if name in split:
        raise SystemExit(f"part {name!r} is already merged")
    clash = sorted(set(manifest["cases_per_code"]) & set(new["cases_per_code"]))
    if clash:
        raise SystemExit(f"{len(clash)} barcodes are already in the review set, nothing merged: {clash[:5]}")
    rows = [line for line in (part / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != new["version_rows"]:
        raise SystemExit(f"{len(rows)} rows against the manifest's {new['version_rows']}: nothing merged")
    with (SET / "stg_silver_versions.jsonl").open("a", encoding="utf-8", newline="\n") as f:
        f.write("".join(line + "\n" for line in rows))
    manifest["cases_per_code"].update(new["cases_per_code"])
    manifest["products"] += new["products"]
    manifest["version_rows"] += new["version_rows"]
    for group, n in new["case_counts"].items():
        manifest["case_counts"][group] = manifest["case_counts"].get(group, 0) + n
    (SET / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    split[name] = sorted(new["cases_per_code"])
    (SET / "split.json").write_text(json.dumps(split, indent=1), encoding="utf-8")
    return {"products": new["products"], "rows": len(rows), "total_products": manifest["products"]}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(merge(sys.argv[1]))
