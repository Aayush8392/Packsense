"""Item 15, step 2: run the event finder on the real daily aggregates and compare it with the events found by hand. Local only, no network.

    python p8_steward/bootstrap/event_report.py [--z 4.0]

Reads p8_steward/data/signal_days.csv and drift_events.csv (written by signal_inventory.py). Prints every event, the drift monitor's file-level alerts by day,
and how the known events fare. Known events (found by hand before this test, from the 2026-10-19 analysis; the India burst is read from the daily India counts):
  India burst: the India count of changed products jumps from tens a day to 271 or more on 2026-10-17 and stays high (to 772 on 21 Oct).
  Owner-heavy file: the file whose window ends 2026-10-06 (owner field on 25.5% of products), seen by the drift monitor as coverage_rise warnings.
  Traces drop: the file whose window ends 2026-10-16 (10.41 traces tags dropped per 100), seen by the drift monitor as one failure_rate alert.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import story_lib as sl  # noqa: E402

DATA = ROOT / "p8_steward" / "data"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--z", type=float, default=sl.Z_LIMIT)
    ap.add_argument("--days", default=str(DATA / "signal_days.csv"))
    ap.add_argument("--drift", default=str(DATA / "drift_events.csv"))
    args = ap.parse_args(argv)
    days = sl.load_days(args.days)
    n_days = len(days["all"])
    events = sl.find_events(days, args.z)
    print(f"{n_days} complete days, z limit {args.z}, {len(events)} events")
    for e in events:
        print(f"  {e.day}  {e.scope:<6}{e.signal:<22}{e.direction:<5}value {e.value:>10.3f}  baseline {e.baseline:>10.3f}  z {e.z:>7}")
    drift = sl.drift_events(args.drift)
    print(f"drift monitor: {len(drift)} coverage or failure-rate alerts and warnings")
    for d in drift:
        print(f"  {d['day']}  {d['level']:<6}{d['check']:<14}{d['detail'][:110]}")
    onset = sl.first_day(events, "india", ("any_products", "nutrition_products"))
    print("known events:")
    print(f"  India burst (onset 2026-10-17): first upward India event {onset or 'none'}")
    for day, label in (("2026-10-06", "owner-heavy file"), ("2026-10-16", "traces drop")):
        hits = [d for d in drift if d["day"] == day]
        print(f"  {label} ({day}): {len(hits)} drift monitor rows")
    quiet = [e for e in events if e.day < "2026-10-17"]
    print(f"events before the India burst (2026-10-01 to 16): {len(quiet)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
