r"""Checks the small pair model (pair_model.py) against the name-only baseline on batches it was not fitted on (roadmap item 19). Counts and rates only.

  .venv\Scripts\python.exe p7_triage_ml\identity\eval_pair_model.py --input D:\off-catalogue-platform\label_studio\packsense_identity\eval_input.SEALED.json
Three rotations: fit on round 1 and two of the round 2 batches (A, B, C), test on the third. 'Cannot tell' pairs are dropped. Weights are the stratum weights of the whole labelled file.
Bar, fixed before any result: the model passes a rotation if its weighted AP is above name-only's on the held-out batch AND the lower end of its 95% interval is not below name-only's lower end;
it replaces name-only only if it passes in at least 2 of the 3 rotations. Each batch is held out once; nothing is tuned on a held-out batch.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_baselines as eb  # noqa: E402
import pair_model as pm  # noqa: E402

BATCHES = ("A", "B", "C")


def evaluate(rows: list[dict]) -> list[dict]:
    """Returns one result per rotation; every row of the held-out batch gets a 'model' score fitted without it."""
    results = []
    for held in BATCHES:
        train = [r for r in rows if r["batch"] != held]
        test = [r for r in rows if r["batch"] == held]
        model = pm.fit(train)
        for r in test:
            r["model"] = pm.predict(model, r)
        results.append({"held": held, "n": len(test), "model": model, "test": test})
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    a = ap.parse_args(argv)
    rows = [r for r in json.load(open(a.input, encoding="utf-8"))["rows"] if r["label"] != "Cannot tell"]
    for r in rows:
        r["pos"] = r["label"] in pm.POSITIVE
    results = evaluate(rows)
    print(f"{len(rows)} labelled pairs ('Cannot tell' dropped); cues: {', '.join(pm.FEATURES)}")
    passed = 0
    print(f"\n{'held out':<9}{'pairs':>6}{'matches':>9}  {'name-only AP (95%)':<28}{'model AP (95%)':<28}{'pass':>5}")
    for res in results:
        t = res["test"]
        ap_n, ap_m = eb.weighted_ap(t, "name_score"), eb.weighted_ap(t, "model")
        (ln, hn), (lm, hm) = eb.bootstrap(t, "name_score"), eb.bootstrap(t, "model")
        ok = ap_m > ap_n and lm >= ln
        passed += ok
        print(f"{res['held']:<9}{res['n']:>6}{sum(1 for r in t if r['pos']):>9}  {ap_n:.3f} ({ln:.3f} to {hn:.3f})   {ap_m:.3f} ({lm:.3f} to {hm:.3f})   {'yes' if ok else 'no':>4}")
    pooled = [dict(r) for res in results for r in res["test"]]
    for i in {r["stratum"] for r in pooled}:   # the pooled pairs stand for the whole stratum again, so recall at K means what it did in the baseline run
        total = sum(r["weight"] for r in rows if r["stratum"] == i)
        in_pool = [r for r in pooled if r["stratum"] == i]
        for r in in_pool:
            r["weight"] = total / len(in_pool)
    print(f"\nall three held-out batches together ({len(pooled)} pairs, every score from a model that did not see the pair):")
    print(f"{'score':<12}{'AP':>7}{'95% interval':>16}{'recall@5k':>11}{'@10k':>8}{'@20k':>8}")
    for key, name in (("name_score", "name-only"), ("model", "pair model")):
        lo, hi = eb.bootstrap(pooled, key)
        print(f"{name:<12}{eb.weighted_ap(pooled, key):>7.3f}   {lo:.3f} to {hi:.3f}{eb.recall_at(pooled, key, 5000):>9.3f}{eb.recall_at(pooled, key, 10000):>8.3f}{eb.recall_at(pooled, key, 20000):>8.3f}")
    print("\nweights (standardised cues, one fit per rotation):")
    for res in results:
        print(f"  without {res['held']}: " + ", ".join(f"{n} {b:+.2f}" for n, b in zip(pm.FEATURES, res["model"]["beta"])))
    print(f"\nverdict: the model passes {passed} of 3 rotations; " + ("it replaces name-only." if passed >= 2 else "name-only stays the deliverable."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
