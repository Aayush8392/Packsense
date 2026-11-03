r"""Pick the pairs for the identity-matching labels and write the Label Studio task file (roadmap item 19). Admin, read-only on production; the output stays OUTSIDE the repo.

  .venv\Scripts\python.exe p7_triage_ml\identity\select_pairs.py --env-file .env --out D:\off-catalogue-platform\label_studio\packsense_identity --round 1

Sample rule (fixed before any label): the candidate pairs are cut into five strata by the baseline name score (identity_lib.STRATA); inside a stratum they are ordered by the md5 of
the two barcodes; round 1 takes the first 50 of each stratum, a later round takes the next ones in the same order, so a longer sample always contains the shorter. The card shows no score
and no stratum, and the tasks are shuffled by the same hash with a salt, so strata are mixed. Photos: OFF's product API, 3 s apart, answers cached outside the repo. Prints counts only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "labelling"))
import cards_lib as cl  # noqa: E402
import identity_lib as il  # noqa: E402
import pairs_data as pdt  # noqa: E402
import select_cards as sc  # noqa: E402

PER_STRATUM = 50
EXTRA = 350
BATCHES = 3
SALT = "packsense-identity-v1"


class FrontPhotos(sc.Off):
    """The same OFF product API as the gate cards (3 s apart, cached), asked only for the front photo."""

    def front(self, code: str) -> str | None:
        if code not in self.cache:
            product = self._json(f"https://world.openfoodfacts.org/api/v2/product/{code}.json?fields=code,selected_images", 3).get("product") or {}
            front = ((product.get("selected_images") or {}).get("front") or {}).get("display") or {}
            self.cache[code] = {"front": sorted(front.items())[0][1] if front else None}
            self.file.write_text(json.dumps(self.cache), encoding="utf-8")
        return self.cache[code]["front"]


def side(p: dict, photo: str | None) -> dict:
    size = cl.amount(p.get("quantity_amount"), p.get("quantity_unit")) if p.get("quantity_amount") else "not recorded"
    return {"name": p["product_name"] or "(no name)", "brand": p["brands"] or "(no brand)", "barcode": p["code"], "pack": size, "link": cl.off_link(p["code"]), "photo": photo}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="count only: no OFF calls, no files")
    a = ap.parse_args(argv)
    if a.env_file:
        pdt.fd.load_env_file(a.env_file)
    products, pairs = pdt.load()
    scored = pdt.score(products, pairs)
    by = {i: [] for i in range(len(il.STRATA))}
    for s in scored:
        by[il.stratum(s["score"])].append((s["a"], s["b"]))
    out = Path(a.out)
    chosen, batches = [], 1
    if a.round == 1:
        for i, lst in by.items():
            for p in il.pick(lst, PER_STRATUM):
                chosen.append((i, p))
    elif a.round == 2:
        # fixed rule: share of the extra pairs per stratum proportional to N_h * sqrt(p_h * (1 - p_h)), p_h = (matches + 0.5) / (n + 1) from round 1; largest-remainder rounding
        rows = json.loads((out / "round1_labels.SEALED.json").read_text(encoding="utf-8"))["rows"]
        match = {"Same product, same size", "Same product, different size"}
        w = []
        for i in range(len(il.STRATA)):
            r = [x for x in rows if x["stratum"] == i]
            ph = (sum(1 for x in r if x["label"] in match) + 0.5) / (len(r) + 1)
            w.append(len(by[i]) * (ph * (1 - ph)) ** 0.5)
        raw = [EXTRA * x / sum(w) for x in w]
        alloc = [int(x) for x in raw]
        for i in sorted(range(len(raw)), key=lambda k: raw[k] - alloc[k], reverse=True)[:EXTRA - sum(alloc)]:
            alloc[i] += 1
        print(f"round 2 allocation per stratum {alloc}")
        done = {tuple(sorted((x["a"], x["b"]))) for x in rows}          # gold is rebuilt daily, so the candidate set drifts a little: skip what round 1 already holds
        for i, lst in by.items():
            for p in il.pick([q for q in lst if tuple(sorted(q)) not in done], alloc[i]):
                chosen.append((i, p))
        batches = BATCHES
    else:
        raise SystemExit("rounds 1 and 2 are defined")
    chosen.sort(key=lambda x: hashlib.md5((SALT + il.pair_key(*x[1])).encode()).hexdigest())
    print(f"strata sizes {[len(v) for v in by.values()]}; round 1 takes {len(chosen)} pairs")
    if a.dry_run:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    off = FrontPhotos(out / "front_cache.json")
    tasks = []
    for n, (i, (ca, cb)) in enumerate(chosen, 1):
        pa, pb = products[ca], products[cb]
        sa, sb = side(pa, off.front(ca)), side(pb, off.front(cb))
        data = {"card": f"pair {n:03d}", **{f"{k}_a": v for k, v in sa.items()}, **{f"{k}_b": v for k, v in sb.items()}}
        tasks.append({"data": data, "meta": {"stratum": i, "a": ca, "b": cb}})
    key = hashlib.sha256("|".join(sorted(il.pair_key(t["meta"]["a"], t["meta"]["b"]) for t in tasks)).encode()).hexdigest()[:16]
    stem = f"round{a.round}"
    (out / f"{stem}_pairs.SEALED.json").write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    (out / f"{stem}_manifest.SEALED.json").write_text(json.dumps({"pairs": len(tasks), "list_hash": key, "per_stratum": PER_STRATUM, "salt": SALT,
                                                                 "strata_sizes": [len(v) for v in by.values()]}), encoding="utf-8")
    if batches > 1:
        size = -(-len(tasks) // batches)
        for b in range(batches):
            part = tasks[b * size:(b + 1) * size]
            for j, t in enumerate(part, 1):
                t["data"]["card"] = f"round 2 batch {'ABC'[b]} {j:03d}"
            (out / f"{stem}_batch{'ABC'[b]}_pairs.SEALED.json").write_text(json.dumps(part, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {len(tasks)} tasks in {batches} file(s); list hash {key}; OFF calls {off.calls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
