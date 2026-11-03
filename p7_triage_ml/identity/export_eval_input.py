r"""Writes the small file the baseline comparison reads (roadmap item 19): for every labelled pair, the label, the stratum, the two product texts, the name-only score and the stratum's weight.

  .venv\Scripts\python.exe p7_triage_ml\identity\export_eval_input.py --env-file .env --dir D:\off-catalogue-platform\label_studio\packsense_identity [--rounds 1,2]
Admin, read-only on production. The output stays on D: (product names are OFF's public data, labels are the owner's): never committed. Prints counts only.
Weight of a pair = (candidate pairs in its stratum) / (labelled pairs in that stratum), so a weighted metric describes all candidate pairs, not only the sample.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import identity_lib as il  # noqa: E402
import pairs_data as pdt  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--dir", required=True)
    ap.add_argument("--rounds", default="1")
    a = ap.parse_args(argv)
    if a.env_file:
        pdt.fd.load_env_file(a.env_file)
    d = Path(a.dir)
    rows = []
    for r in a.rounds.split(","):
        rows += json.loads((d / f"round{r}_labels.SEALED.json").read_text(encoding="utf-8"))["rows"]
    products, pairs = pdt.load()
    scored = {(s["a"], s["b"]): s for s in pdt.score(products, pairs)}
    sizes = [0] * len(il.STRATA)
    for s in scored.values():
        sizes[il.stratum(s["score"])] += 1
    n_h = [sum(1 for x in rows if x["stratum"] == i) for i in range(len(il.STRATA))]
    out = []
    for x in rows:
        key = tuple(sorted((x["a"], x["b"])))
        pa, pb = products[x["a"]], products[x["b"]]
        s = scored.get(key)
        card = x["card"]
        out.append({"label": x["label"], "stratum": x["stratum"], "weight": sizes[x["stratum"]] / n_h[x["stratum"]],
                    "batch": card.split()[-2] if card.startswith("round 2 batch") else "R1",
                    "size": il.size_relation(pa["qty"], pb["qty"]), "gap": il.nutrition_gap(pa, pb),
                    "name_score": s["score"] if s else None, "text_a": f"{pa['brands'] or ''} {pa['product_name'] or ''}".strip(),
                    "text_b": f"{pb['brands'] or ''} {pb['product_name'] or ''}".strip()})
    (d / "eval_input.SEALED.json").write_text(json.dumps({"strata_sizes": sizes, "labelled_per_stratum": n_h, "rows": out}, ensure_ascii=False), encoding="utf-8")
    print(f"labelled pairs {len(out)}; strata sizes now {sizes}; labelled per stratum {n_h}; pairs no longer candidates {sum(1 for r in out if r['name_score'] is None)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
