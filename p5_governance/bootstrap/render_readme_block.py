"""Rewrite the generated grants block of p5_governance/README.md from grants.yml.

  python p5_governance/bootstrap/render_readme_block.py

CI fails (tests/test_grants.py) when the block is stale, so run this after every change to grants.yml.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import grants_lib as gl  # noqa: E402

README = HERE.parent / "README.md"
PATTERN = re.compile(r"<!-- grants:begin -->\n.*?\n<!-- grants:end -->", re.S)


def main() -> int:
    text = README.read_text(encoding="utf-8")
    block = f"<!-- grants:begin -->\n```sql\n{gl.render_sql(gl.load_spec())}\n```\n<!-- grants:end -->"
    if not PATTERN.search(text):
        sys.exit("README.md has no <!-- grants:begin --> ... <!-- grants:end --> markers")
    new = PATTERN.sub(lambda _: block, text)
    README.write_text(new, encoding="utf-8", newline="\n")
    print("README grants block", "updated" if new != text else "already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
