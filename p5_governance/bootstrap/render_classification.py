"""Write DATA_CLASSIFICATION.md (repo root) from classification.yml, the silver contract and gold_columns.json.

  python p5_governance/bootstrap/render_classification.py          # rewrite the file
  python p5_governance/bootstrap/render_classification.py --check  # exit 1 if the file is stale or the classification is unsound
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import classification_lib as cl  # noqa: E402


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    spec = cl.load_spec()
    bad = cl.problems(spec)
    if bad:
        print("\n".join(bad))
        return 1
    text = cl.render(spec)
    if "--check" in argv:
        have = cl.DOC_PATH.read_text(encoding="utf-8") if cl.DOC_PATH.exists() else ""
        if have != text:
            print("DATA_CLASSIFICATION.md is stale: run python p5_governance/bootstrap/render_classification.py")
            return 1
        print("DATA_CLASSIFICATION.md is current")
        return 0
    cl.DOC_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {cl.DOC_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
