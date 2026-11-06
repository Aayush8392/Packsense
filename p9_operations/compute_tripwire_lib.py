"""The compute tripwire (roadmap: the three jobs before items 24 and 25): turns hourly compute DBU from `system.billing.usage` into a rolling 24-hour total
and says whether it is above the warning line.

What is measured (2026-11-06, from the hourly series in tests/fixtures/compute_usage_hourly.json): compute = the SKUs JOBS_SERVERLESS_COMPUTE + SERVERLESS_SQL_COMPUTE;
the highest rolling 24 hour total ever seen is 68.2 DBU (ending 28 Oct 06:00 UTC, the day the free daily limit locked every job); the highest without a lock is
64.3 DBU (ending 3 Nov 20:00 UTC). The warning line is 50 DBU, below both, so a backfill that is heading for the lock is flagged before it gets there.
Production alone on a quiet day is about 7 to 12 DBU (Sun 1 Nov 6.9, Sat 24 Oct 8.1, Sun 25 Oct 11.8); weekly jobs add to the Monday.

Honest limits: billing lags the clock by about 5 hours, so this is a brake for the owner's own manual runs (backfills, labelling-time reads), not a guard against a
sudden spike; one lock event only means 58 to 68 is a bracket, not a rule; billing figures stay OFF the public site (decision of 2026-10-21).
Pure Python: the notebook passes the rows in, so every rule is testable without Databricks.
"""
from __future__ import annotations

import datetime as dt

WARN_DBU = 50.0
WINDOW_HOURS = 24
COMPUTE_GROUPS = ("jobs", "sql")      # 'other' (network and the like) is not compute and never counts toward the limit
HOUR_FORMAT = "%Y-%m-%d %H"


def hourly_compute(hours: dict[str, dict[str, float]]) -> list[tuple[dt.datetime, float]]:
    """A gap-free hourly series of compute DBU from the first to the last hour that has usage (an hour with no row counts as 0)."""
    if not hours:
        return []
    stamps = {dt.datetime.strptime(k, HOUR_FORMAT): sum(v.get(g, 0.0) for g in COMPUTE_GROUPS) for k, v in hours.items()}
    t, end, out = min(stamps), max(stamps), []
    while t <= end:
        out.append((t, stamps.get(t, 0.0)))
        t += dt.timedelta(hours=1)
    return out


def rolling_totals(series: list[tuple[dt.datetime, float]], window: int = WINDOW_HOURS) -> list[tuple[dt.datetime, float]]:
    """The total of the `window` hours that END with each hour (only where a full window exists)."""
    return [(series[i][0], sum(v for _, v in series[i - window + 1: i + 1])) for i in range(window - 1, len(series))]


def evaluate(hours: dict[str, dict[str, float]], warn: float = WARN_DBU) -> dict:
    """Latest rolling total, the highest in the data, and whether the latest is over the line. `over_line_hours` lists the hours whose window was over it."""
    totals = rolling_totals(hourly_compute(hours))
    if not totals:
        return {"ok": False, "reason": "less than 24 hours of billing data", "latest": None}
    latest_at, latest = totals[-1]
    peak_at, peak = max(totals, key=lambda x: x[1])
    return {"ok": latest <= warn, "warn": warn, "latest_ending": latest_at.strftime(HOUR_FORMAT), "latest_dbu": round(latest, 1),
            "peak_ending": peak_at.strftime(HOUR_FORMAT), "peak_dbu": round(peak, 1), "over_line_hours": sum(1 for _, v in totals if v > warn)}
