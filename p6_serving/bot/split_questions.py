"""Split the question-bot test questions into a working set and a held-out set (Phase C, item 14).

The working set is used to write the answer catalogue and to tune the matcher. The held-out set is read by nobody until the final measurement, so the hit rate
is not inflated by writing answers while looking at the test questions. The split is a fixed rule (a hash of the group), so it can be re-run and checked.

Questions that belong together stay together: rewordings (1.1, 1.1b, 1.1c), questions with identical text, and the near-duplicates listed in SAME below.
Run from the repo root: python p6_serving/bot/split_questions.py
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = "packsense-bot-split-2026"
HELD_OUT_SHARE = 1 / 3

# near-duplicates that must land on the same side (found by reading the list: same thing asked in two topics)
SAME = [
    ("14.1", "14.2"), ("14.10", "15.8"), ("7.9", "14.8"), ("5.9", "14.9"), ("7.16", "14.4"), ("14.18", "5.10"), ("10.4", "15.16"), ("15.6", "2.13"),
    ("15.2", "4.1"), ("6.28", "15.17"), ("16.3", "16.4"), ("3.16", "14.13"), ("12.4", "12.16"), ("6.5", "14.22"),
]


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            qid, text, kind = line.split("|")
            rows.append({"id": qid, "text": text, "kind": kind})
    return rows


def base_id(qid: str) -> str:
    return re.sub(r"[a-z]+$", "", qid)


def stratum(qid: str) -> str:
    return "decline" if qid.startswith("17.") else qid.split(".")[0]


def groups(rows: list[dict]) -> dict[str, list[dict]]:
    """Union-find over: same base id (rewordings), same normalised text, and the SAME pairs. Returns group key -> its rows."""
    parent = {r["id"]: r["id"] for r in rows}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    by_base, by_text = defaultdict(list), defaultdict(list)
    for r in rows:
        by_base[base_id(r["id"])].append(r["id"])
        by_text[re.sub(r"\W+", " ", r["text"].lower()).strip()].append(r["id"])
    for ids in list(by_base.values()) + list(by_text.values()):
        for other in ids[1:]:
            union(ids[0], other)
    present = set(parent)
    for a, b in SAME:
        for x, y in ((a, b),):
            ids_a = [i for i in present if base_id(i) == x]
            ids_b = [i for i in present if base_id(i) == y]
            if ids_a and ids_b:
                union(ids_a[0], ids_b[0])
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        out[find(r["id"])].append(r)
    return dict(out)


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Per stratum (topic, or the decline block), groups in hash order go to the held-out set until it holds about a third of that stratum's rows."""
    held: set[str] = set()
    by_stratum: dict[str, list[tuple[str, list[dict]]]] = defaultdict(list)
    for key, members in groups(rows).items():
        by_stratum[min(stratum(m["id"]) for m in members)].append((key, members))
    for s, items in by_stratum.items():
        total = sum(len(m) for _, m in items)
        target = round(total * HELD_OUT_SHARE)
        taken = 0
        for key, members in sorted(items, key=lambda kv: hashlib.sha256(f"{SEED}:{min(m['id'] for m in kv[1])}".encode()).hexdigest()):
            if taken >= target:
                break
            held.update(m["id"] for m in members)
            taken += len(members)
    return [r for r in rows if r["id"] not in held], [r for r in rows if r["id"] in held]


def write(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(f"{r['id']}|{r['text']}|{r['kind']}\n" for r in rows), encoding="utf-8")


def main() -> None:
    original = load(HERE / "questions_all.psv")
    added = load(HERE / "questions_added_heldout.psv")        # approved 2026-10-24: hard declines and rewordings of working-set questions; held-out only
    working, held = split(original)
    held = held + added
    rows = original + added
    write(HERE / "questions_working.psv", working)
    write(HERE / "questions_heldout.psv", held)
    count = lambda rs: {s: sum(1 for r in rs if stratum(r["id"]) == s) for s in sorted({stratum(r["id"]) for r in rows}, key=lambda x: (x == "decline", int(x) if x.isdigit() else 99))}   # noqa: E731
    report = {"all": len(rows), "working": len(working), "held_out": len(held), "held_out_share": round(len(held) / len(rows), 3),
              "per_topic": {s: {"working": count(working)[s], "held_out": count(held)[s]} for s in count(rows)}}
    (HERE / "split_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
