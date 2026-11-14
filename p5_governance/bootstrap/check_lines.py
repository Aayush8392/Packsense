"""Run the licence gate on the nightly photo-read line shards of the app's data folder.

  python p5_governance/bootstrap/check_lines.py <app data folder>      # exit 1 and list every violation, or print OK and exit 0

The folder is p6_serving/app/public/data (it holds cards/splits.json and, when there are any, lines/<prefix>.json). No lines folder is fine: the lines are optional."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import licence_gate  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    bad = licence_gate.check_lines(argv[0])
    if bad:
        print("\n".join(f"VIOLATION {b}" for b in bad))
        return 1
    print("OK: the line shards pass the licence gate (or there are none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
