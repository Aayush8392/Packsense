r"""Fix-rate analysis (roadmap Phase D item 21): how long a flag stays open before a contributor fixes it, by severity, flag family and top category. Counts only, read-only.

  .venv\Scripts\python.exe p7_triage_ml\analysis\fix_rate.py --env-file .env [--min-spells 200] [--schema workspace.packsense_snapshots]
Admin, read-only. Source: `snapshot_flag_events` (what changed between two weekly snapshots) and `snapshot_features` (the product's categories). Prints no barcode and no product.

A spell starts when a flag APPEARS between two snapshots (a flag already open at the first snapshot has no known start and is left out) and lasts until it disappears. Time is counted in
snapshot steps (about a week each). The spell ends as FIXED when the flag disappeared, the product was edited and the flag's family did not just come back under another name (the same rule
as the triage label). A disappearance in one of the two OFF-side jump weeks, without an edit, or by a rename ends the spell as CENSORED (we do not know whether a person fixed it), and so does
the end of our data. Survival is the Kaplan-Meier estimate; "fixed by week k" is 1 minus survival at k. Only the first spell of a (product, flag) is used.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "p4_modelling" / "bootstrap"))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / "p9_operations"))
import fixture_databricks as fd  # noqa: E402
from snapshot_lib import family_key as family_of  # noqa: E402  (the one definition of a flag family)
from triage_labels import JUMP_WEEKS  # noqa: E402

HORIZONS = (1, 2, 4, 8)


def kaplan_meier(spells: list[tuple[int, int, int]]) -> list[tuple[int, int, int, float]]:
    """`spells` are (duration in steps, event 1 = fixed or 0 = censored, count). Returns (t, at_risk, fixed, survival) at every t where somebody was fixed."""
    by_t: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for t, e, n in spells:
        by_t[t][0 if e else 1] += n
    at_risk = sum(n for _, _, n in spells)
    s, out = 1.0, []
    for t in sorted(by_t):
        fixed, cens = by_t[t]
        if fixed and at_risk:
            s *= 1 - fixed / at_risk
            out.append((t, at_risk, fixed, s))
        at_risk -= fixed + cens
    return out


def fixed_by(curve: list[tuple[int, int, int, float]], k: int) -> float:
    """Share fixed by step k: 1 - survival at the last event time <= k (1 - 1 = 0 before the first fix)."""
    s = 1.0
    for t, _, _, surv in curve:
        if t <= k:
            s = surv
    return 1 - s


def median_steps(curve: list[tuple[int, int, int, float]]) -> int | None:
    for t, _, _, surv in curve:
        if surv <= 0.5:
            return t
    return None


def spells_sql(schema: str) -> str:
    jumps = ", ".join(f"DATE '{d}'" for d in JUMP_WEEKS)
    e = f"{schema}.snapshot_flag_events"
    return f"""
with snaps as (select d, row_number() over (order by d) k from (select date_to d from {e} union select date_from d from {e}) x),
app as (
    select code, severity, flag, family, date_to d_a,
           row_number() over (partition by code, severity, flag order by date_to) rn
    from {e} where event = 'appeared'
),
first_app as (select * from app where rn = 1),
dis as (
    select a.code, a.severity, a.flag, a.family, a.d_a, e.date_to d_d, e.edited, e.family_remains,
           row_number() over (partition by a.code, a.severity, a.flag order by e.date_to) rn
    from first_app a join {e} e on e.code = a.code and e.severity = a.severity and e.flag = a.flag and e.event = 'disappeared' and e.date_to > a.d_a
),
first_dis as (select * from dis where rn = 1),
last_k as (select max(k) k from snaps),
cat as (
    select f.code, f.snapshot_date, get(f.categories, 0) top_cat
    from {schema}.snapshot_features f
)
select a.severity, a.flag family_flag, a.family, coalesce(c.top_cat, '(no category on record)') top_cat,
       (coalesce(sd.k, (select k from last_k)) - sa.k) as steps,
       case when d.d_d is not null and d.edited and not d.family_remains and d.d_d not in ({jumps}) then 1 else 0 end as fixed,
       count(*) n
from first_app a
join snaps sa on sa.d = a.d_a
left join first_dis d on d.code = a.code and d.severity = a.severity and d.flag = a.flag
left join snaps sd on sd.d = d.d_d
left join cat c on c.code = a.code and c.snapshot_date = a.d_a
group by 1, 2, 3, 4, 5, 6
""".strip()


def report(rows: list[tuple], min_spells: int) -> None:
    groups: dict[str, dict[tuple, Counter]] = {"severity": defaultdict(Counter), "family": defaultdict(Counter), "top category (error and warning flags in scope)": defaultdict(Counter)}
    for sev, flag, _fam, cat, steps, fixed, n in rows:
        groups["severity"][sev][(steps, fixed)] += n
        groups["family"][f"{sev}: {family_of(flag)}"][(steps, fixed)] += n
        if sev in ("error", "warning") and cat != "(no category on record)":
            groups["top category (error and warning flags in scope)"][cat][(steps, fixed)] += n
    for title, g in groups.items():
        print(f"\n== by {title}: spells, share fixed by 1 / 2 / 4 / 8 steps (Kaplan-Meier), median steps to fix")
        ranked = sorted(g.items(), key=lambda kv: -sum(kv[1].values()))
        shown = 0
        for key, c in ranked:
            n = sum(c.values())
            if n < min_spells:
                continue
            curve = kaplan_meier([(t, e, k) for (t, e), k in c.items()])
            med = median_steps(curve)
            print(f"{key[:60]:<60}{n:>9}   " + " ".join(f"{fixed_by(curve, h):>6.3f}" for h in HORIZONS) + f"   {med if med is not None else 'not reached'}")
            shown += 1
            if shown >= 15 and title != "severity":
                break
        small = sum(1 for _, c in ranked if sum(c.values()) < min_spells)
        print(f"({small} groups with fewer than {min_spells} spells are not listed)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file")
    ap.add_argument("--schema", default="workspace.packsense_snapshots")
    ap.add_argument("--min-spells", type=int, default=200)
    a = ap.parse_args(argv)
    if a.env_file:
        fd.load_env_file(a.env_file)
    w = fd.client()
    raw = fd.run_sql(w, spells_sql(a.schema)).result.data_array
    rows = [(r[0], r[1], r[2], r[3], int(r[4]), int(r[5]), int(r[6])) for r in raw]
    total = sum(r[6] for r in rows)
    fixed = sum(r[6] for r in rows if r[5])
    print(f"spells (first appearance of a flag after the first snapshot): {total}; ended as fixed: {fixed}; censored: {total - fixed}")
    report(rows, a.min_spells)
    return 0


if __name__ == "__main__":
    sys.exit(main())
