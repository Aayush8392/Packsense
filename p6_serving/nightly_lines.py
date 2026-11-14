"""Builds the site's nightly photo-read line shards from the private nightly dataset (A123 (4), amended 2026-11-13).

  HF_NIGHTLY_READ_TOKEN=... python p6_serving/nightly_lines.py <app_data_folder> <nightly_repo_id>

Reads `lines/current.json` (every line the nightly job still holds as valid) and `input/candidates.json` (the daily Databricks export of each product's STORED values) from the
private dataset, and keeps a line only when
  1. it passes the line validator (the nightly job's own, `line_record.validate_line`, so a hand-edited or damaged line is dropped),
  2. its product is a candidate of the latest export, and
  3. the hash of that candidate's stored values equals the line's `record_hash` (the same function the nightly job used: if the record changed after the line was made, the line is stale and is
     not shown).
The surviving lines are written as `<app_data_folder>/lines/<prefix>.json`, one file per card shard (the same lookup rule as the cards, from `cards/splits.json`), without the hash, and the
licence gate (`licence_gate.check_lines`) runs on the result before this script succeeds. Lines are OPTIONAL: with no token or no repo set, or no `lines/current.json` in the dataset, the lines
folder is removed and the build goes on without lines. A configured dataset that cannot be read stops the build (a stale site must be noticed). Standard library only; counts only are printed.
"""
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "p8_steward" / "nightly"))
sys.path.insert(0, str(HERE.parent / "p5_governance"))
import fetch_site_data as fs  # noqa: E402
import licence_gate  # noqa: E402
import line_record as lr  # noqa: E402

CURRENT, CANDIDATES = "lines/current.json", "input/candidates.json"
PUBLIC_COLUMNS = [c for c in lr.COLUMNS if c != "record_hash"]


class LinesError(Exception):
    pass


def select_lines(current, candidates_doc) -> tuple[list[dict], dict]:
    """(the lines to publish, counts). `current`: {code: line}; `candidates_doc`: {"exported": ..., "candidates": [{code, stored, new}]}."""
    counts = {"held": 0, "kept": 0, "invalid": 0, "not_a_candidate": 0, "stale": 0}
    if not isinstance(current, dict):
        raise LinesError("lines/current.json is not an object")
    cands = candidates_doc.get("candidates") if isinstance(candidates_doc, dict) else None
    if not isinstance(cands, list):
        raise LinesError("input/candidates.json has no list of candidates")
    stored = {c["code"]: c["stored"] for c in cands if isinstance(c, dict) and isinstance(c.get("code"), str) and isinstance(c.get("stored"), dict)}
    keep = []
    for code, line in current.items():
        counts["held"] += 1
        if not isinstance(line, dict) or line.get("code") != code or lr.validate_line(line):
            counts["invalid"] += 1
            continue
        if code not in stored:
            counts["not_a_candidate"] += 1
            continue
        try:
            same = lr.record_hash(stored[code]) == line["record_hash"]
        except (TypeError, ValueError):
            same = False
        if not same:
            counts["stale"] += 1
            continue
        keep.append({k: line[k] for k in PUBLIC_COLUMNS})
        counts["kept"] += 1
    keep.sort(key=lambda r: r["code"])
    return keep, counts


def write_shards(lines: list[dict], data: Path) -> int:
    """Writes lines/<prefix>.json under `data` (replacing any earlier lines folder). Returns the number of files."""
    folder = data / "lines"
    if folder.exists():
        shutil.rmtree(folder)
    if not lines:
        return 0
    try:
        splits = set(json.loads((data / "cards" / "splits.json").read_text(encoding="utf-8"))["splits"])
    except (OSError, ValueError, KeyError, TypeError):
        raise LinesError("cards/splits.json cannot be read, so the lines cannot be placed") from None
    by_prefix: dict[str, list[dict]] = {}
    for line in lines:
        by_prefix.setdefault(licence_gate.shard_for(line["code"], splits), []).append(line)
    folder.mkdir(parents=True)
    for prefix, rows in by_prefix.items():
        (folder / f"{prefix}.json").write_text(json.dumps({"version": 1, "lines": rows}, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return len(by_prefix)


def build(data: Path, repo: str, token: str, opener=None) -> dict:
    kw = {"opener": opener} if opener else {}
    try:
        current_bytes = fs._get(repo, CURRENT, token, prefix="", **kw)
    except fs.FetchError as e:
        if str(e).endswith("HTTP 404"):
            write_shards([], data)
            return {"files": 0, "held": 0, "kept": 0, "note": "the dataset has no lines yet"}
        raise LinesError(f"{e}") from None
    try:
        cands_bytes = fs._get(repo, CANDIDATES, token, prefix="", **kw)
    except fs.FetchError as e:
        raise LinesError(f"{e}") from None
    try:
        current, cands = json.loads(current_bytes), json.loads(cands_bytes)
    except ValueError:
        raise LinesError("a nightly file is not valid JSON") from None
    lines, counts = select_lines(current, cands)
    counts["files"] = write_shards(lines, data)
    bad = licence_gate.check_lines(data)
    if bad:
        shutil.rmtree(data / "lines", ignore_errors=True)
        raise LinesError("the licence gate refused the lines: " + "; ".join(bad[:5]))
    return counts


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        print(__doc__)
        return 2
    data, repo = Path(argv[0]), argv[1].strip()
    token = os.environ.get("HF_NIGHTLY_READ_TOKEN", "").strip()
    if not repo or not token:
        write_shards([], data)
        print("nightly lines: not configured (no repo or no token), the site is built without lines")
        return 0
    try:
        counts = build(data, repo, token)
    except (LinesError, fs.FetchError, OSError) as e:
        print(f"nightly lines failed: {e}")
        return 1
    print("nightly lines: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
