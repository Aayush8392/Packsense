"""Item 15 (Phase C): the daily signal table and the event finder of the story engine (context amendment A47). Code only, no model.

A signal is one number per complete UTC day and scope ('all' or 'india') computed by gold. The event finder compares each day with the median of the days before it
(at most 14, at least 5) and reports a day when it sits far outside the usual spread, so a quiet week gives no event and a burst gives one on its first day.
It reports what moved and by how much; it never says why (A46: the layer describes, it does not guess).
"""
from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

SIGNALS = ("any_products", "new_products", "unseen_edits", "nutrition_products", "ingredients_products", "india_share")
WINDOW = 14
MIN_HISTORY = 5
Z_LIMIT = 4.0
SCALE_FLOOR = 0.15           # the spread is never taken as less than this share of the baseline (a very steady series would flag noise)
MIN_BASELINE = {"any_products": 100, "new_products": 100, "unseen_edits": 20, "nutrition_products": 50, "ingredients_products": 20, "india_share": 0.0}


@dataclass(frozen=True)
class Event:
    day: str
    scope: str
    signal: str
    value: float
    baseline: float
    spread: float
    z: float
    direction: str


def load_days(path: str | Path) -> dict[str, dict[str, dict[str, float]]]:
    """scope -> day -> signal -> value, with the India share of the day's changed products added to the 'all' scope."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.setdefault(r["scope"], {})[r["change_date"]] = {k: (float(r[k]) if r[k] != "" else 0.0) for k in SIGNALS if k in r}
    for day, row in out.get("all", {}).items():
        india = out.get("india", {}).get(day, {}).get("any_products", 0.0)
        row["india_share"] = india / row["any_products"] if row["any_products"] else 0.0
    return out


def _spread(values: list[float], baseline: float) -> float:
    mad = statistics.median(abs(v - baseline) for v in values)
    return max(1.4826 * mad, SCALE_FLOOR * abs(baseline), 1e-9)


def find_events(days: dict[str, dict[str, dict[str, float]]], z_limit: float = Z_LIMIT) -> list[Event]:
    events: list[Event] = []
    for scope, by_day in days.items():
        ordered = sorted(by_day)
        for i, day in enumerate(ordered):
            history = ordered[max(0, i - WINDOW):i]
            if len(history) < MIN_HISTORY:
                continue
            for sig in SIGNALS:
                if sig not in by_day[day] or sig == "india_share" and scope != "all":
                    continue
                past = [by_day[d][sig] for d in history if sig in by_day[d]]
                if len(past) < MIN_HISTORY:
                    continue
                base = statistics.median(past)
                value = by_day[day][sig]
                if max(base, value) < MIN_BASELINE[sig]:
                    continue
                spread = _spread(past, base)
                z = (value - base) / spread
                if abs(z) >= z_limit:
                    events.append(Event(day, scope, sig, value, base, spread, round(z, 1), "up" if z > 0 else "down"))
    return sorted(events, key=lambda e: (e.day, e.scope, e.signal))


def file_window_end(subject: str) -> str | None:
    """The UTC day a delta file's window ends, from its name 'openfoodfacts_products_<start>_<end>.json.gz'."""
    parts = subject.replace(".json.gz", "").split("_")
    if len(parts) >= 4 and parts[-1].isdigit() and parts[-2].isdigit():
        return datetime.fromtimestamp(int(parts[-1]), tz=timezone.utc).date().isoformat()
    return None


def drift_events(path: str | Path) -> list[dict]:
    """The drift monitor's per-file alerts and warnings about a coverage or failure-rate change, dated by the end of the file's window."""
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            day = file_window_end(r["subject"])
            if day and r["check_name"] in ("coverage_rise", "failure_rate", "coverage_drop"):
                out.append({"day": day, "level": r["level"], "check": r["check_name"], "detail": r["detail"]})
    return sorted(out, key=lambda e: (e["day"], e["check"], e["detail"]))


def first_day(events: list[Event], scope: str, signals: tuple[str, ...]) -> str | None:
    days = [e.day for e in events if e.scope == scope and e.signal in signals and e.direction == "up"]
    return min(days) if days else None


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days
