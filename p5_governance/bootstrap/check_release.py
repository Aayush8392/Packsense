"""Run the licence gate on a release folder.

  python p5_governance/bootstrap/check_release.py <folder>      # exit 1 and list every violation, or print OK and exit 0

The folder holds release_manifest.json and the files it lists. P6's export pipeline calls p5_governance.licence_gate.check_release() as its last step
before publishing; this command is the same check for a human. A violation never repeats a matched value."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import licence_gate  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    bad = licence_gate.check_release(argv[0])
    if bad:
        print("\n".join(f"VIOLATION {b}" for b in bad))
        return 1
    print("OK: the release passes the licence gate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
