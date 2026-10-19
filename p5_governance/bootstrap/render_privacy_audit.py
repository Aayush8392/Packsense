"""Write PRIVACY_AUDIT.md (repo root) from p5_governance/privacy_audit.json.

  python p5_governance/bootstrap/render_privacy_audit.py          # rewrite the file
  python p5_governance/bootstrap/render_privacy_audit.py --check  # exit 1 if the file is stale or the stored result holds more than counts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import privacy_audit_lib as pal  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    res = pal.load_result()
    bad = pal.only_counts(res)
    if bad:
        print("\n".join(bad))
        return 1
    text = pal.render(res)
    if "--check" in argv:
        have = pal.DOC_PATH.read_text(encoding="utf-8") if pal.DOC_PATH.exists() else ""
        if have != text:
            print("PRIVACY_AUDIT.md is stale: run python p5_governance/bootstrap/render_privacy_audit.py")
            return 1
        print("PRIVACY_AUDIT.md is current")
        return 0
    pal.DOC_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {pal.DOC_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
