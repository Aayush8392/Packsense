"""p7_triage_ml/replay_lib.py: the catalogue as we held it at the end of a past UTC day (roadmap item 6, the replay harness).

Pure functions that build SQL over the gold tables `product_history` and `product_flag_spans`; nothing here connects to anything.
The rule is the one of the dbt macros `history_as_of` and `spans_as_of` (p4_modelling/macros/replay.sql), written in seconds: a
day d means the instant T = the last second of d (UTC). `test_replay_lib.py` keeps the two in step.

  period open at T : valid_from_t <= T and (valid_to_t is null or valid_to_t > T)
  flag span open at T : first_seen_t <= T and (vanished_at_t is null or vanished_at_t > T)

Nothing dated after T can satisfy either predicate (the leakage guard). What a replay is NOT: the state of OFF on that day. It is the
state of OUR copy as of that day, and a product with no version dated on or before T is absent (the seed arrived late, and about 35% of
consecutive versions have unseen edits between them). Consistency with silver and the daily quality fact is proven by the dbt tests
`replay_matches_silver` and `replay_matches_quality_fact`; accuracy against OFF is not claimed.
"""
from __future__ import annotations

import datetime as dt
import re

DAY_SECONDS = 86400
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")

HISTORY_OPEN = "{a}valid_from_t <= {t} and ({a}valid_to_t is null or {a}valid_to_t > {t})"
SPANS_OPEN = "{a}first_seen_t <= {t} and ({a}vanished_at_t is null or {a}vanished_at_t > {t})"


def end_of_day_t(day: dt.date | str) -> int:
    """Unix seconds of the last second of the UTC day."""
    if isinstance(day, str):
        day = dt.date.fromisoformat(day)
    return (day - dt.date(1970, 1, 1)).days * DAY_SECONDS + DAY_SECONDS - 1


def _ident(name: str) -> str:
    if not _NAME.match(name):
        raise ValueError(f"not a plain table or alias name: {name!r}")
    return name


def _t(t: int) -> int:
    if isinstance(t, bool) or not isinstance(t, int):
        raise TypeError("t must be an integer number of seconds")
    return t


def history_open(t: int, alias: str = "") -> str:
    a = _ident(alias) + "." if alias else ""
    return HISTORY_OPEN.format(a=a, t=_t(t))


def spans_open(t: int, alias: str = "") -> str:
    a = _ident(alias) + "." if alias else ""
    return SPANS_OPEN.format(a=a, t=_t(t))


def state_as_of_sql(t: int, history_table: str) -> str:
    """Every column of the periods that were open at T: the catalogue state, nutrients included."""
    return f"select * from {_ident(history_table)} where {history_open(t)}"


def open_flags_as_of_sql(t: int, spans_table: str) -> str:
    return f"select * from {_ident(spans_table)} where {spans_open(t)}"


def counts_as_of_sql(t: int, history_table: str, spans_table: str) -> str:
    """One row: products held at T and open flag spans per severity. Counts only, safe to print."""
    h, s = _ident(history_table), _ident(spans_table)
    return (
        f"select (select count(distinct code) from {h} where {history_open(t)}) as products_held, "
        f"(select count(*) from {s} where {spans_open(t)} and severity = 'error') as open_error, "
        f"(select count(*) from {s} where {spans_open(t)} and severity = 'warning') as open_warning, "
        f"(select count(*) from {s} where {spans_open(t)} and severity = 'info') as open_info, "
        f"(select count(*) from {s} where {spans_open(t)} and severity = 'bug') as open_bug"
    )


def assert_no_future(rows: list[dict], t: int) -> None:
    """The leakage guard for a consumer: every returned period or span must have been knowable at T."""
    for r in rows:
        for key in ("valid_from_t", "first_seen_t"):
            if r.get(key) is not None and r[key] > t:
                raise AssertionError(f"{key}={r[key]} is after T={t}")
