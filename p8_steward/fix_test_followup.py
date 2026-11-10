"""Look closer at the proposals that differ from OFF's fix ('valid alternatives'): their STRUCTURE, and what the product's LATER history says. Read-only on local files.

  python p8_steward/fix_test_followup.py code      -> the code baseline on the development products

Rules fixed 2026-11-08 before this was run:
 (1) STRUCTURE. Fields a proposal changes = fields whose proposed value differs from the pre-fix value; fields the fix changed = those where the key differs from the pre-fix value.
     relation = no_shared_field (no field changed by both) | same_fields_* / overlapping_fields_* ; '_near' when EVERY shared field is within 2.5 times the allowance of the 10% rule
     (about 25%), else '_far'. Field score = the share of the fields the fix changed on which the repaired record agrees with the key.
 (2) LATER HISTORY. The latest observation after the fix (weekly snapshots after the fix week, silver versions after it, per 100 g) is compared with (a) the fix key: STABLE when it still agrees,
     OVERTURNED when not, and (b) the repaired record: LATER AGREES when the repaired record agrees with the latest observation on the group's fields. A product with no later observation
     is counted as such and left out of both.
Nothing here changes the primary result; these are separate figures.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import answer_key_lib as akl  # noqa: E402
import fix_test_lib as t  # noqa: E402
import history_key_scan_check as hk  # noqa: E402

NEAR = 2.5
NUT = {"energy_kj": "energy_kj", "energy_kcal": "energy_kcal", "fat": "fat", "saturated_fat": "saturated_fat", "carbohydrates": "carbohydrates", "sugars": "sugars",
       "fiber": "fiber", "proteins": "proteins", "salt": "salt", "sodium": "sodium"}


def changed_by(before: dict, after: dict) -> list[str]:
    return [f for f in after if f not in before or abs(after[f] - before[f]) > 1e-6 * max(1.0, abs(before[f]))]


def allowance(field: str, truth: float) -> float:
    rel, floor = akl.TOLERANCE.get(field, (0.10, 0.05))
    return max(rel * abs(truth), floor)


def relation(before: dict, repaired: dict, key: dict) -> str:
    mine, fix = set(changed_by(before, repaired)), set(changed_by(before, key))
    shared = mine & fix
    if not shared:
        return "no_shared_field"
    near = all(abs(repaired[f] - key[f]) <= NEAR * allowance(f, key[f]) for f in shared)
    return ("same_fields" if mine == fix else "overlapping_fields") + ("_near" if near else "_far")


def field_score(before: dict, repaired: dict, key: dict) -> float | None:
    fix = changed_by(before, key)
    return None if not fix else sum(akl.field_matches(f, repaired.get(f), key[f]) for f in fix) / len(fix)


def latest_after(fix_date: str, features: list[dict], silver: list[dict]) -> dict | None:
    """The newest observation (per 100 g values) strictly after the fix week; None when there is none."""
    cut = datetime.fromisoformat(fix_date).replace(tzinfo=timezone.utc).timestamp()
    obs = []
    for r in features:
        if r["snapshot_date"] > fix_date:
            vals = {f: float(r[f"b_{f}"]) for f in NUT if r.get(f"b_{f}") is not None}
            if vals:
                obs.append((datetime.fromisoformat(r["snapshot_date"]).replace(tzinfo=timezone.utc).timestamp(), vals))
    for r in silver:
        if r.get("nutrition_per") == "100g" and float(r["last_modified_t"]) > cut:
            vals = {f: float(r[f]) for f in NUT if r.get(f) is not None}
            if vals:
                obs.append((float(r["last_modified_t"]), vals))
    return max(obs, key=lambda o: o[0])[1] if obs else None


def judge(row: dict, proposal: dict | None, features: list[dict], silver: list[dict]) -> dict:
    cls = t.classify(row, proposal)
    out = {"code": row["code"], "class": cls}
    if not proposal:
        return out
    b, k = t.before(row), t.key(row)
    repaired = {**b, **{f: v for f, v in proposal.items() if v is not None}}
    group = t.group_of_row(row)
    out["relation"], out["field_score"] = relation(b, repaired, k), field_score(b, repaired, k)
    later = latest_after(row["date_to"], features, silver)
    if later is None:
        out["later"] = "no_later_observation"
    else:
        out["key_status"] = "stable" if akl.matches_key_for_group(k, later, group)["match"] else "overturned"
        out["later_agrees"] = akl.matches_key_for_group(repaired, later, group)["match"]
    return out


def load_followup():
    feats, silver = {}, {}
    for line in (hk.REVIEW / "fix_dev_later_features.jsonl").read_text(encoding="utf8").splitlines():
        r = json.loads(line)
        feats.setdefault(r["code"], []).append(r)
    for line in (hk.REVIEW / "fix_dev_later_silver.jsonl").read_text(encoding="utf8").splitlines():
        r = json.loads(line)
        silver.setdefault(r["code"], []).append(r)
    return feats, silver


def summary(results: list[dict]) -> dict:
    out: dict = {}
    for cls in ("agrees", "valid_alternative"):
        rs = [r for r in results if r["class"] == cls]
        sc = [r["field_score"] for r in rs if r.get("field_score") is not None]
        later = [r for r in rs if "key_status" in r]
        out[cls] = {"n": len(rs), "relation": {k: sum(r.get("relation") == k for r in rs) for k in sorted({r.get("relation") for r in rs if r.get("relation")})},
                    "mean_field_score": round(sum(sc) / len(sc), 3) if sc else None, "no_later_observation": sum(r.get("later") == "no_later_observation" for r in rs),
                    "key_stable": sum(r["key_status"] == "stable" for r in later), "key_overturned": sum(r["key_status"] == "overturned" for r in later),
                    "later_agrees_with_repair": sum(r["later_agrees"] for r in later)}
    return out


def main() -> None:
    dev = json.loads((hk.REVIEW / "fix_test_dev.json").read_text(encoding="utf8"))
    feats, silver = load_followup()
    results = [judge(r, t.code_proposal(r), feats.get(r["code"], []), silver.get(r["code"], [])) for r in dev]
    print(json.dumps(summary(results), indent=1))




def hybrid_report(model: str) -> None:
    """The clean-key alternatives of HYBRID B (agent first, code as fallback), looked at with the structure, later-history and scan checks of this module."""
    sys.path.insert(0, str(Path(__file__).resolve().parent / "bootstrap"))
    import dev_ocr_reader as dr  # noqa: E402
    import fix_test_agent as fa  # noqa: E402
    import reader_decision as rd  # noqa: E402
    dev = json.loads((hk.REVIEW / "fix_test_dev.json").read_text(encoding="utf8"))
    readings = json.loads(fa.files("dev", model)[1].read_text(encoding="utf-8"))
    feats, silver = load_followup()
    alts, agrees_from = [], {"agent": 0, "code": 0}
    for row in dev:
        if not t.clean_key(row):
            continue
        text = dr.scan_text(row["code"], fa.VERSION)[:6000]
        dec = rd.decide(t.before(row), readings.get(row["code"], {}).get("reading"), text, t.group_of_row(row), fa.VERSION)
        prop = t.agent_proposal(dec)
        filled = t.complete_partners(t.before(row), dec.get("reading100") or {}, prop) if prop else None
        by_agent = bool(filled) and not t.fc.violations({**t.before(row), **filled})
        proposal = t.hybrid_agent_first(row, filled)
        res = judge(row, proposal, feats.get(row["code"], []), silver.get(row["code"], []))
        res["by"] = "agent" if by_agent else "code"
        if res["class"] == "agrees":
            agrees_from[res["by"]] += 1
        elif res["class"] == "valid_alternative":
            scan = hk.REVIEW / "ocr_json" / f"{row['code']}.json"
            res["printed"] = t.printed_side(row, proposal, hk.scan_text(json.loads(scan.read_text(encoding="utf8")))) if scan.exists() else "no_scan_file"
            alts.append(res)
    print("agreements by source:", agrees_from)
    print("alternatives:", len(alts), "| by source:", {k: sum(a["by"] == k for a in alts) for k in ("agent", "code")})
    print("relation:", {k: sum(a.get("relation") == k for a in alts) for k in sorted({a.get("relation") for a in alts})})
    sc = [a["field_score"] for a in alts if a.get("field_score") is not None]
    print("mean field score:", round(sum(sc) / len(sc), 3))
    later = [a for a in alts if "key_status" in a]
    print("key stable later:", sum(a["key_status"] == "stable" for a in later), "overturned:", sum(a["key_status"] == "overturned" for a in later),
          "no later observation:", len(alts) - len(later), "| later state agrees with the proposal:", sum(a["later_agrees"] for a in later))
    print("printed in the scan (proposal vs fix):", {k: sum(a["printed"] == k for a in alts) for k in sorted({a["printed"] for a in alts})})
    for a in alts[:0]:
        print(a)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "code":
        main()
    elif len(sys.argv) > 2 and sys.argv[1] == "hybrid":
        hybrid_report(sys.argv[2])
    else:
        sys.exit(__doc__)
