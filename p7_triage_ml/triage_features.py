"""The features of the flag-triage model: what is known about an open flag AS OF the snapshot it was open in (roadmap Phase D item 17).

Every column below uses only rows of snapshot t and earlier snapshots, never a later one (the labels, in `triage_labels.py`, are the only thing that
looks ahead). Today's nutrition would contain the fix, so the nutrition columns come from `snapshot_features`, the product as THAT snapshot held it.

Per open flag (one row of `snapshot_open_flags`):
  family, severity            what the flag is
  flag_age                    snapshots the flag has been open in a row up to and including t (1 = first snapshot we saw it in; a flag open at our
                              first snapshot is also 1, so a lower bound)
  n_open_flags, n_open_errors the product's in-scope open flags at t, and how many of them are errors
  edited_since_prev           whether the product's last-modified time moved since the previous snapshot (NULL when it was not flagged then)
  days_since_edit             days between the product's last edit and the newest edit of any flagged product in that snapshot (a stand-in for the
                              snapshot's own time, which is plain arithmetic and the same on both engines)
  serving_size, brand, n_categories, n_nutrients, max_mass_g
  nutrition (ten core values per 100 g)
What a product's OFF flags say about its numbers is NOT added here: the family already carries that, and the rule verdicts on OFF's aggregated nutrients
agree poorly with OFF's flags for five of our 11 rules (context file, A71).

Plain SQL with two per-engine expressions (a map lookup and a list length), so the same text runs on Databricks and on DuckDB, where the tests run it.
"""
from __future__ import annotations

NUTRIENT_COLUMNS = (("energy_kj", "energy-kj"), ("energy_kcal", "energy-kcal"), ("fat", "fat"), ("saturated_fat", "saturated-fat"),
                    ("carbohydrates", "carbohydrates"), ("sugars", "sugars"), ("proteins", "proteins"), ("salt", "salt"), ("sodium", "sodium"),
                    ("fiber", "fiber"))

ENGINES = {
    "spark": {"nutrient": "try_element_at(f.nutrients, '{k}')", "list_len": "greatest(coalesce(size({x}), 0), 0)"},
    "duckdb": {"nutrient": "map_extract_value(f.nutrients, '{k}')", "list_len": "coalesce(len({x}), 0)"},
}


def feature_sql(flags: str = "snapshot_open_flags", features: str = "snapshot_features", engine: str = "spark") -> str:
    """One row per open flag with the columns above. `flags` and `features` may be qualified names or parenthesised subqueries."""
    if engine not in ENGINES:
        raise ValueError(f"engine must be one of {sorted(ENGINES)}")
    e = ENGINES[engine]
    nutrients = ",\n       ".join(f"{e['nutrient'].format(k=key)} as {col}" for col, key in NUTRIENT_COLUMNS)
    return f"""
with snaps as (
    select snapshot_date, row_number() over (order by snapshot_date) as k from (select distinct snapshot_date from {flags}) d
),
ranked as (
    select f.snapshot_sha, f.snapshot_date, s.k, f.code, f.severity, f.flag, f.family,
           s.k - row_number() over (partition by f.code, f.severity, f.flag order by s.k) as grp,
           count(*) over (partition by f.snapshot_sha, f.code) as n_open_flags,
           sum(case when f.severity = 'error' then 1 else 0 end) over (partition by f.snapshot_sha, f.code) as n_open_errors
    from {flags} f join snaps s on s.snapshot_date = f.snapshot_date
),
aged as (
    select r.*, row_number() over (partition by r.code, r.severity, r.flag, r.grp order by r.k) as flag_age from ranked r
),
feat as (
    select ft.snapshot_sha, ft.code, ft.lm, ft.serving_size, ft.brand, ft.categories, ft.nutrients, ft.n_nutrients, ft.max_mass_g, s.k,
           lag(ft.lm) over (partition by ft.code order by s.k) as prev_lm,
           lag(s.k) over (partition by ft.code order by s.k) as prev_k,
           max(ft.lm) over (partition by ft.snapshot_sha) as newest_lm
    from {features} ft join snaps s on s.snapshot_date = ft.snapshot_date
)
select a.snapshot_sha, a.snapshot_date, a.code, a.severity, a.flag, a.family, a.flag_age, a.n_open_flags, a.n_open_errors,
       case when f.prev_k = a.k - 1 then (case when f.lm <> f.prev_lm then 1 else 0 end) end as edited_since_prev,
       (f.newest_lm - f.lm) / 86400.0 as days_since_edit,
       f.serving_size, f.brand, {e['list_len'].format(x='f.categories')} as n_categories, f.n_nutrients, f.max_mass_g,
       {nutrients}
from aged a left join feat f on f.snapshot_sha = a.snapshot_sha and f.code = a.code
""".strip()


def training_sql(steps: int, flags: str = "snapshot_open_flags", features: str = "snapshot_features", events: str = "snapshot_flag_events",
                 presence: str = "snapshot_presence_events", engine: str = "spark") -> str:
    """Labels and features together: one row per open flag, the label columns first. Rows with `outcome = 'unlabelled'` are kept (with their
    reason) so they can be counted; the model uses only 'positive' and 'negative'."""
    from triage_labels import label_sql
    return f"""
with labels as ({label_sql(steps, flags, events, presence)}),
feats as ({feature_sql(flags, features, engine)})
select l.snapshot_sha, l.snapshot_date, l.code, l.severity, l.flag, l.family, l.target_date, l.outcome, l.reason,
       f.flag_age, f.n_open_flags, f.n_open_errors, f.edited_since_prev, f.days_since_edit, f.serving_size, f.brand, f.n_categories,
       f.n_nutrients, f.max_mass_g, {", ".join("f." + c for c, _ in NUTRIENT_COLUMNS)}
from labels l join feats f on f.snapshot_sha = l.snapshot_sha and f.code = l.code and f.severity = l.severity and f.flag = l.flag
""".strip()
