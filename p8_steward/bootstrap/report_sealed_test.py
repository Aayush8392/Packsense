"""The report of the sealed test (A121 paragraphs 8 and 9). Pure analysis of one finished reader run: it changes nothing and calls no model.

  python p8_steward/bootstrap/report_sealed_test.py --part test --version v3rows

Definitions (fixed before the run, same as A121):
  proposal          the reader's action is 'change to reading' or 'fill in' (the public status 'appears to differ'); RIGHT when every field of the flagged group is within 10% of the key
  match verdict     the action starts with 'no change' ('appears to match'); RIGHT when the stored record agrees with the key on the flagged group
  silent miss       a 'no change' verdict on a record that does NOT agree with the key (the check said 'matches' and was wrong)
  abstention        the action starts with 'abstain' ('not assessed'); coverage = 1 - abstention rate
  band              the median word height (px) of the raw scan; edges under 15, 15 to 20, 20 to 30, 30 to 50, 50 and up
Bar: proposals right at least 90% (point) AND Wilson 95% lower bound at least 80%; fewer than 40 proposals = inconclusive (a fail for publication).
A band is switched on only with at least 15 keyed proposals AND a lower bound of at least 80%.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

BAND_EDGES = [0, 15, 20, 30, 50]
BAND_NAMES = ["under 15 px", "15 to 20 px", "20 to 30 px", "30 to 50 px", "50 px and up"]
POINT_BAR, LOWER_BAR, MIN_PROPOSALS, BAND_MIN_N, FAMILY_MIN_N = 0.90, 0.80, 40, 15, 15
# Weights of the weighted pooled bar (A121 (k), owner 2026-11-06): the share of each family among the India nutrition ERROR flags open in production,
# counted 2026-11-06 by p8_steward/notebooks/count_flag_mix.py (1,264 flags: A 438, B 57, C 442, D 157, E 170). Fixed here before the freeze; the freeze record carries them.
FAMILY_WEIGHTS = {"A_energy_mismatch": 438, "B_salt_vs_sodium": 57, "C_values_too_large": 442, "D_sums_too_large": 157, "E_other_nutrition": 170}


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """95% Wilson score interval for k of n (0, 0 when n is 0)."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def band_of(height: float | None) -> str:
    if height is None:
        return "no word height"
    i = max(j for j, e in enumerate(BAND_EDGES) if height >= e)
    return BAND_NAMES[i]


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": (k / n) if n else None, "lower95": lo, "upper95": hi}


def summarise(rows: list[dict]) -> dict:
    """rows: {code, action, stored_right, proposal_right (bool|None), height}. Returns every figure of the report."""
    n = len(rows)
    props = [r for r in rows if r["action"] in ("change to reading", "fill in") and not r.get("unscorable")]      # rule (b): a proposal on a field the key does not hold is dropped, right or wrong
    matches = [r for r in rows if r["action"].startswith("no change")]
    absts = [r for r in rows if r["action"].startswith("abstain")]
    p_right = sum(bool(r["proposal_right"]) for r in props)
    out = {"cards": n, "dropped_unscorable": sum(1 for r in rows if r["action"] in ("change to reading", "fill in") and r.get("unscorable")), "proposals": rate(p_right, len(props)), "match_verdicts": rate(sum(bool(r["stored_right"]) for r in matches), len(matches)),
           "silent_misses": rate(sum(not r["stored_right"] for r in matches), n), "abstentions": rate(len(absts), n), "coverage": rate(n - len(absts), n)}
    pr = out["proposals"]
    if len(props) < MIN_PROPOSALS:
        out["bar"] = f"INCONCLUSIVE ({len(props)} proposals, fewer than {MIN_PROPOSALS}): a fail for publication"
    elif pr["rate"] >= POINT_BAR and pr["lower95"] >= LOWER_BAR:
        out["bar"] = "PASS"
    else:
        out["bar"] = "FAIL"
    out["match_bar"] = ("PASS" if matches and out["match_verdicts"]["rate"] >= POINT_BAR and out["match_verdicts"]["lower95"] >= LOWER_BAR else "not passed (not public)")
    bands = {}
    for name in BAND_NAMES + ["no word height"]:
        bp = [r for r in props if band_of(r["height"]) == name]
        b = rate(sum(bool(r["proposal_right"]) for r in bp), len(bp))
        b["switched_on"] = len(bp) >= BAND_MIN_N and b["lower95"] >= LOWER_BAR
        bands[name] = b
    out["bands"] = bands
    return out


def weighted_bar(fam_summary: dict, weights: dict[str, float] = FAMILY_WEIGHTS, z: float = 1.959964) -> dict:
    """The weighted pooled bar of A121 (k) (owner's choice, 6 Nov): each family's proposal precision is weighted by the family's share of the open India error flags
    in production, so the easy family C cannot dominate. Weights are renormalised over the families that have at least one scorable proposal (the weight left out is
    reported). The interval is the Agresti-Coull one per family combined as a stratified estimate: p~ = (k + z^2/2) / (n + z^2); variance = sum W^2 p~(1-p~) / (n + z^2);
    lower = weighted p~ - z sqrt(variance). Overlapping strata (a card in several families) make the families not independent: the interval is approximate, and the
    unweighted pooled bar stays printed beside it. PASS needs: weighted point estimate >= 0.90, lower >= 0.80 and at least 40 proposals in the one-case-per-product pool.
    """
    fams = {f: s["proposals"] for f, s in fam_summary.items() if f in weights and s["proposals"]["n"] > 0}
    total_w = sum(weights[f] for f in fams)
    if not fams or total_w == 0:
        return {"point": None, "lower95": None, "families_used": [], "weight_left_out": 1.0, "bar": "INCONCLUSIVE (no family has a scorable proposal)"}
    point = lower_c = var = 0.0
    for f, pr in fams.items():
        w = weights[f] / total_w
        k, n = pr["k"], pr["n"]
        pt = (k + z * z / 2) / (n + z * z)
        point += w * (k / n)
        lower_c += w * pt
        var += w * w * pt * (1 - pt) / (n + z * z)
    lower = max(0.0, lower_c - z * math.sqrt(var))
    return {"point": point, "lower95": lower, "families_used": sorted(fams), "weight_left_out": round(1 - total_w / sum(weights.values()), 4),
            "per_family": {f: {"k": p["k"], "n": p["n"], "weight": round(weights[f] / total_w, 4)} for f, p in fams.items()}}


def family_verdict(rate_: dict) -> str:
    """A121 (k), owner's final reading (6 Nov): a family is JUDGED only with at least FAMILY_MIN_N scorable proposals, by the same bar as the pooled one (point 90%, Wilson 95% lower end 80%);
    a smaller family is reported with its interval and never passes or fails (a pool that small cannot meet the bar even for a human)."""
    if rate_["n"] < FAMILY_MIN_N:
        return f"reported only (fewer than {FAMILY_MIN_N} proposals)"
    return "PASS" if rate_["rate"] >= POINT_BAR and rate_["lower95"] >= LOWER_BAR else "FAIL"


def weighted_verdict(wb: dict, proposals_total: int) -> str:
    if wb["point"] is None:
        return wb["bar"]
    if proposals_total < MIN_PROPOSALS:
        return f"INCONCLUSIVE ({proposals_total} proposals, fewer than {MIN_PROPOSALS}): a fail for publication"
    return "PASS" if wb["point"] >= POINT_BAR and wb["lower95"] >= LOWER_BAR else "FAIL"


def families_of(error_tags) -> list[str]:
    """The flag families a product carries, from OFF's ERROR tags (`data_quality_errors_tags`), in the fixed priority order (A121 paragraph 11 (j))."""
    import review_set_lib as rsl
    if isinstance(error_tags, str):
        error_tags = json.loads(error_tags) if error_tags.startswith("[") else [error_tags]
    found = {rsl.group_of(t) for t in (error_tags or [])} - {None}
    return [g for g in rsl.ALL_GROUPS if g in found]


def median_height(code: str, ocr_dir: Path) -> float | None:
    import scan_layout as sl
    f = ocr_dir / f"{code}.json"
    if not f.exists():
        return None
    ws = sl.words_of(json.loads(f.read_text(encoding="utf-8") or "{}"))
    return statistics.median(w["h"] for w in ws) if ws else None


def fmt(x: dict) -> str:
    return "n/a" if not x["n"] else f"{x['k']} of {x['n']} = {x['rate']:.1%} (95% interval {x['lower95']:.1%} to {x['upper95']:.1%})"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--readings", help="score another readings file (an exploratory model run) instead of the sealed one; the report file gets a suffix")
    a = ap.parse_args()
    import answer_key_lib as ak
    import dev_ocr_reader as dr
    import fix_candidates as fc
    key, (_, out_file) = dr.usable_cards(a.part, a.version), dr.paths(a.part, a.version)
    if a.readings:
        out_file = Path(a.readings)
    readings = json.loads(out_file.read_text(encoding="utf-8"))
    rows_by: dict = {}
    for line in (dr.SET / "stg_silver_versions.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["code"] not in rows_by or r["last_modified_t"] > rows_by[r["code"]]["last_modified_t"]:
                rows_by[r["code"]] = r
    rows = []
    for code, entry in key.items():
        group, truth = entry["group"], entry["per100"]
        stored_ok = ak.matches_key_for_group(fc.clean(rows_by[code]), truth, group)
        d = dr.decide(fc.clean(rows_by[code]), (readings.get(code) or {}).get("reading"), dr.scan_text(code, a.version), group, a.version)
        cmp = ak.matches_key_for_group(d["per100"], truth, group) if d["per100"] else None
        pr = cmp["match"] if cmp else None
        rows.append({"code": code, "group": group[0], "action": d["action"], "stored_right": stored_ok["match"], "proposal_right": pr, "height": median_height(code, dr.SET / "ocr_json"),
                     "dropped": d["dropped"], "unscorable": bool(cmp and cmp["compared"] == 0)})
    s = summarise(rows)
    print(f"[{a.part} {a.version}] cards {s['cards']}\n")
    print("proposals ('appears to differ') right:", fmt(s["proposals"]), "->", s["bar"])
    print("'appears to match' verdicts right:   ", fmt(s["match_verdicts"]), "->", s["match_bar"])
    print("silent misses (of all cards):        ", fmt(s["silent_misses"]))
    print(f"proposals dropped (the key lacks the field they concern; rule (b)): {s['dropped_unscorable']}")
    print("abstentions ('not assessed'):        ", fmt(s["abstentions"]))
    print("coverage (acted on):                 ", fmt(s["coverage"]))
    print("\nprecision of proposals by median word height:")
    for name, b in s["bands"].items():
        if b["n"]:
            print(f"  {name:15} {fmt(b)}  {'ON' if b['switched_on'] else 'off (fewer than 15 proposals or lower bound under 80%)'}")
    print("\nmisses to tag with a cause (local only):")
    for r in rows:
        if r["action"] in ("change to reading", "fill in") and not r["proposal_right"] and not r.get("unscorable"):
            print("  wrong proposal ", r["code"], r["group"], band_of(r["height"]), r["action"])
        elif r["action"].startswith("no change") and not r["stored_right"]:
            print("  silent miss    ", r["code"], r["group"], band_of(r["height"]), r["action"])
    fam_rows: dict[str, list[dict]] = {}
    for code, entry in key.items():
        stored = fc.clean(rows_by[code])
        for fam in families_of(rows_by[code].get("data_quality_errors_tags")):
            d = dr.decide(stored, (readings.get(code) or {}).get("reading"), dr.scan_text(code, a.version), fam, a.version)
            truth = entry["per100"]
            cmp = ak.matches_key_for_group(d["per100"], truth, fam) if d["per100"] else None
            fam_rows.setdefault(fam, []).append({"code": code, "action": d["action"], "stored_right": ak.matches_key_for_group(stored, truth, fam)["match"],
                                                 "proposal_right": cmp["match"] if cmp else None, "height": None, "unscorable": bool(cmp and cmp["compared"] == 0)})
    print("\nBY FLAG FAMILY (a card counts in every family it carries: overlapping strata, never added together; the bar above stays one case per product):")
    fam_summary = {}
    for fam, frows in sorted(fam_rows.items()):
        fs = summarise(frows)
        fam_summary[fam] = fs
        fs["verdict"] = family_verdict(fs["proposals"])
        print(f"  {fam:20} cards {fs['cards']:3} | proposals right {fmt(fs['proposals'])} -> {fs['verdict']} | matches right {fmt(fs['match_verdicts'])} | not assessed {fs['abstentions']['k']}")
    s["families"] = fam_summary
    wb = weighted_bar(fam_summary)
    wb["bar"] = weighted_verdict(wb, s["proposals"]["n"])
    s["weighted_bar"] = wb
    if wb["point"] is not None:
        print(f"\nWEIGHTED BAR (A121 (k): families weighted by the production stock of open India error flags; the pass/fail of the weighted reading): "
              f"{wb['point']:.1%} (lower end {wb['lower95']:.1%}; approximate interval) -> {wb['bar']}")
        print("  weights used:", {f: f"{v['weight']:.1%} ({v['k']} of {v['n']})" for f, v in wb["per_family"].items()}, "| weight left out:", wb["weight_left_out"])
    else:
        print("\nWEIGHTED BAR:", wb["bar"])
    suffix = f"__{out_file.stem.split('__', 1)[1]}" if a.readings and "__" in out_file.stem else ""
    (dr.SET / f"sealed_report_{a.part}_{a.version}{suffix}.json").write_text(json.dumps({"summary": s, "rows": rows}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
