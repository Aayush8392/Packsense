"""Run the licence gate's showcase rules on the committed four-product showcase file.

  python p5_governance/bootstrap/check_showcase.py p6_serving/showcase/showcase.json      # exit 1 and list every violation, or print OK and exit 0

The Pages workflow runs this before the site is built; the same check runs inside the export notebook before the file is written. A violation never
repeats a matched value."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import licence_gate  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    bad = licence_gate.check_showcase(argv[0])
    if bad:
        print("\n".join(f"VIOLATION {b}" for b in bad))
        return 1
    print("OK: the showcase passes the licence gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
