"""The labels of the flag-triage model (roadmap Phase D item 17; unit and window agreed with the owner on 2026-10-26).

Unit: a flag that is OPEN on a product in the weekly OFF snapshot t (a row of `snapshot_open_flags`). Label, for a window of W snapshots:
  positive    the flag is gone within the window (the product was in both snapshots around the change), the product was edited, and the flag's family did not simply
              come back under another name (that is a rename, not a fix)
  negative    the flag is still open in snapshot t + W
  unlabelled  anything else, kept apart with a reason so it is counted and never guessed:
              censored (t + W is after the newest snapshot), product_left, renamed, no_edit (the flag vanished without an edit: OFF changed its
              own rule), jump_week (the flag vanished in a week where OFF changed its rules or taxonomy and thousands of flags went at once),
              not_seen_again (the flag is not open at t + W and no change event explains it)
A snapshot step is one position in the list of snapshot dates (they are a week apart, give or take a day), not seven days of arithmetic.
The first disappearance inside the window decides; a flag that goes and comes back is still positive (it was fixed once).

Measured 2026-10-26: the two jump weeks are the pairs ending 2026-09-20 (103,284 disappearances against 27,000 to 46,000 in a normal week) and
2026-10-25 (1,272 fixed errors against 290 to 490). Why OFF's data moved those weeks is not known.

Only the SQL text is built here. It uses plain SQL (window functions, left joins, `exists`) so the same text runs on Databricks and on DuckDB, where
the tests run it against a slice of the real tables (`tests/fixtures/triage_slice.json`).
"""
from __future__ import annotations

JUMP_WEEKS = ("2026-09-20", "2026-10-25")        # the pair ENDING on these snapshot dates is not used for labels
OUTCOMES = ("positive", "negative", "unlabelled")
REASONS = ("fixed", "still_open", "censored", "product_left", "renamed", "no_edit", "jump_week", "not_seen_again")


def label_sql(steps: int, flags: str = "snapshot_open_flags", events: str = "snapshot_flag_events", presence: str = "snapshot_presence_events",
              jump_weeks: tuple[str, ...] = JUMP_WEEKS) -> str:
    """One row per open flag: snapshot_sha, snapshot_date, code, severity, flag, family, lm, target_date, outcome, reason.
    `steps` is W, the window in snapshots. The three table names may be qualified (`workspace.packsense_snapshots.snapshot_open_flags`)."""
    if not isinstance(steps, int) or steps < 1:
        raise ValueError("steps must be a positive integer")
    jumps = ", ".join(f"DATE '{d}'" for d in jump_weeks) if jump_weeks else "DATE '1900-01-01'"
    return f"""
with snaps as (
    select snapshot_date, row_number() over (order by snapshot_date) as k from (select distinct snapshot_date from {flags}) d
),
base as (
    select f.snapshot_sha, f.snapshot_date, s.k, f.code, f.severity, f.flag, f.family, f.lm
    from {flags} f join snaps s on s.snapshot_date = f.snapshot_date
),
tgt as (
    select b.*, s2.snapshot_date as target_date
    from base b left join snaps s2 on s2.k = b.k + {steps}
),
ev as (
    select t.snapshot_sha, t.code, t.severity, t.flag, e.date_to as ev_date, e.edited as ev_edited, e.family_remains as ev_renamed,
           row_number() over (partition by t.snapshot_sha, t.code, t.severity, t.flag order by e.date_to) as rn
    from tgt t
    join {events} e on e.code = t.code and e.severity = t.severity and e.flag = t.flag and e.event = 'disappeared'
                   and e.date_to > t.snapshot_date and e.date_to <= t.target_date
),
first_ev as (select * from ev where rn = 1),
gone as (
    select t.snapshot_sha, t.code, t.flag, 1 as left_flag
    from tgt t
    where exists (select 1 from {presence} p where p.code = t.code and p.event = 'left'
                  and p.date_to > t.snapshot_date and p.date_to <= t.target_date)
),
still as (
    select t.snapshot_sha, t.code, t.severity, t.flag, 1 as still_open
    from tgt t
    where exists (select 1 from {flags} f2 where f2.snapshot_date = t.target_date and f2.code = t.code and f2.severity = t.severity and f2.flag = t.flag)
)
select t.snapshot_sha, t.snapshot_date, t.code, t.severity, t.flag, t.family, t.lm, t.target_date,
       case
           when t.target_date is null then 'unlabelled'
           when e.ev_date is not null and e.ev_date not in ({jumps}) and not e.ev_renamed and e.ev_edited then 'positive'
           when e.ev_date is not null then 'unlabelled'
           when g.left_flag is not null then 'unlabelled'
           when s.still_open is not null then 'negative'
           else 'unlabelled'
       end as outcome,
       case
           when t.target_date is null then 'censored'
           when e.ev_date is not null and e.ev_date in ({jumps}) then 'jump_week'
           when e.ev_date is not null and e.ev_renamed then 'renamed'
           when e.ev_date is not null and not e.ev_edited then 'no_edit'
           when e.ev_date is not null then 'fixed'
           when g.left_flag is not null then 'product_left'
           when s.still_open is not null then 'still_open'
           else 'not_seen_again'
       end as reason
from tgt t
left join first_ev e on e.snapshot_sha = t.snapshot_sha and e.code = t.code and e.severity = t.severity and e.flag = t.flag
left join gone g on g.snapshot_sha = t.snapshot_sha and g.code = t.code and g.flag = t.flag
left join still s on s.snapshot_sha = t.snapshot_sha and s.code = t.code and s.severity = t.severity and s.flag = t.flag
""".strip()
