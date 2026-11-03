"""Counts the candidate pairs by baseline-score stratum (item 19). Counts only, read-only.

  python p7_triage_ml/identity/count_strata.py [--env-file .env]
"""
import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import identity_lib as il  # noqa: E402
import pairs_data as pdt  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    a = ap.parse_args(argv)
    if a.env_file:
        pdt.fd.load_env_file(a.env_file)
    products, pairs = pdt.load()
    scored = pdt.score(products, pairs)
    print(f"products {len(products)}, candidate pairs {len(pairs)}")
    c = Counter(il.stratum(s["score"]) for s in scored)
    proxy = Counter(il.stratum(s["score"]) for s in scored if s["gap"] is not None and s["gap"] <= 0.10)
    print("stratum (name score)      pairs   nutrition-close pairs (<= 10%)   same size / different / unknown among those")
    for i, (lo, hi) in enumerate(il.STRATA):
        sizes = Counter(s["size"] for s in scored if il.stratum(s["score"]) == i and s["gap"] is not None and s["gap"] <= 0.10)
        print(f"[{lo:.2f}, {min(hi, 1.0):.2f}]  {c[i]:>10}  {proxy[i]:>14}   {sizes['same']:>6} / {sizes['different']:>6} / {sizes['unknown']:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
