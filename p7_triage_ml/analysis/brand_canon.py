r"""Brand canonicalisation (roadmap Phase D item 21): which raw brand strings are one brand. Read-only on gold; writes one CSV OUTSIDE the repo.

  .venv\Scripts\python.exe p7_triage_ml\analysis\brand_canon.py --env-file .env --out D:\off-catalogue-platform\_sandbox\brand_canonical.csv [--sample 25]
Input: the first free-text brand of every product we hold (already lower-cased by gold) with its product count. Two rules, both conservative (nothing is guessed):
  R2 key      accents folded, `&` read as `and`, punctuation and spacing removed, a leading `the` and trailing legal words (ltd, limited, pvt, inc, gmbh, sa, ...) dropped;
              two strings with the same non-empty key are one brand.
  R3 close    inside a block of keys that share their first four letters, two keys that differ by at most 2 characters in length and have a similarity of at least 0.94
              (difflib) are one brand, and only when both are 6 or more letters long (short names differ by one letter and mean different brands).
The canonical name of a group is its most frequent raw string. A string that matches nothing stays itself. The CSV holds raw string, canonical, rule and product count.
Prints counts and a sample of merged groups (brand strings are public data), no barcode.
"""
from __future__ import annotations

import argparse
import difflib
import random
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "p4_modelling" / "bootstrap"))
import fixture_databricks as fd  # noqa: E402

LEGAL = {"ltd", "limited", "pvt", "private", "inc", "incorporated", "llc", "gmbh", "sa", "sas", "spa", "srl", "bv", "ag", "co", "corp", "corporation", "company", "plc", "oy", "ab", "as", "nv", "sl", "sarl", "ltda", "kg"}
NON_WORD = re.compile(r"[^a-z0-9]+")
MIN_LEN, MAX_LEN_GAP, MIN_RATIO, BLOCK = 6, 2, 0.94, 4


def brand_key(raw: str | None) -> str:
    """R2: the comparison key of a brand string (empty when nothing is left)."""
    folded = unicodedata.normalize("NFKD", (raw or "").lower().replace("&", " and "))
    words = NON_WORD.sub(" ", "".join(c for c in folded if not unicodedata.combining(c))).split()
    if words and words[0] == "the" and len(words) > 1:
        words = words[1:]
    while len(words) > 1 and words[-1] in LEGAL:
        words = words[:-1]
    return "".join(words)


def group_brands(counts: dict[str, int]) -> dict[str, tuple[str, str]]:
    """Maps every raw string to (canonical raw string, rule): rule is `same` (it is its own canonical), `key` (R2) or `close` (R3)."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for raw in counts:
        by_key[brand_key(raw) or raw].append(raw)
    parent = {k: k for k in by_key}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    blocks: dict[str, list[str]] = defaultdict(list)
    for k in by_key:
        if len(k) >= MIN_LEN:
            blocks[k[:BLOCK]].append(k)
    close_pairs = set()
    for keys in blocks.values():
        keys.sort()
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if abs(len(a) - len(b)) <= MAX_LEN_GAP and difflib.SequenceMatcher(None, a, b).ratio() >= MIN_RATIO:
                    ra, rb = find(a), find(b)
                    if ra != rb:
                        parent[rb] = ra
                    close_pairs.add(a)
                    close_pairs.add(b)
    members: dict[str, list[str]] = defaultdict(list)
    for k, raws in by_key.items():
        members[find(k)].extend(raws)
    out = {}
    for raws in members.values():
        canon = max(raws, key=lambda r: (counts[r], -len(r), r))
        keys = {brand_key(r) or r for r in raws}
        for r in raws:
            if r == canon:
                out[r] = (canon, "same")
            else:
                out[r] = (canon, "key" if (brand_key(r) or r) == (brand_key(canon) or canon) else "close")
        if len(keys) > 1 and not any((brand_key(r) or r) in close_pairs for r in raws):
            raise AssertionError("a group of several keys must come from close matches")
    return out


def main(argv=None) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")        # brand strings carry accents and typographic quotes
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--schema", default="packsense_gold")
    ap.add_argument("--out")
    ap.add_argument("--sample", type=int, default=25)
    a = ap.parse_args(argv)
    if a.env_file:
        fd.load_env_file(a.env_file)
    w = fd.client()
    rows = fd.run_sql(w, f"select first_brand, count(*) from workspace.{a.schema}.product_history where is_latest_observed = 1 and first_brand is not null group by 1").result.data_array
    counts = {r[0]: int(r[1]) for r in rows}
    mapping = group_brands(counts)
    n_raw = len(counts)
    n_key = len({brand_key(r) or r for r in counts})
    n_canon = len({c for c, _ in mapping.values()})
    merged = {r: m for r, m in mapping.items() if m[1] != "same"}
    products = sum(counts.values())
    moved = sum(counts[r] for r in merged)
    print(f"raw brand strings {n_raw} on {products} products; distinct keys after R2 {n_key}; canonical brands after R2+R3 {n_canon}")
    print(f"strings merged into another: {len(merged)} (R2 key {sum(1 for m in merged.values() if m[1] == 'key')}, R3 close {sum(1 for m in merged.values() if m[1] == 'close')}); "
          f"products whose brand string changes: {moved} ({moved / products:.1%})")
    groups = defaultdict(list)
    for r, (c, rule) in merged.items():
        groups[c].append((r, rule))
    rng = random.Random(20261103)
    for rule in ("key", "close"):
        pool = sorted(c for c, v in groups.items() if any(x[1] == rule for x in v))
        print(f"\n-- {min(a.sample, len(pool))} of {len(pool)} groups with a merge by rule {rule}: canonical <- merged variants (products)")
        for c in rng.sample(pool, min(a.sample, len(pool))):
            print(f"  {c!r} ({counts[c]}) <- " + ", ".join(f"{r!r} ({counts[r]})" for r, _ in groups[c][:6]))
    if a.out:
        import csv
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            cw = csv.writer(f)
            cw.writerow(["raw", "canonical", "rule", "products"])
            for r in sorted(mapping):
                cw.writerow([r, mapping[r][0], mapping[r][1], counts[r]])
        print(f"\nwrote {len(mapping)} rows to {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
