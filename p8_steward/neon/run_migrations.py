"""Apply the review-store migrations to Neon (item 22): `python p8_steward/neon/run_migrations.py status|apply --env-file .env`.

A migration is a file `NNN_name.sql` in this folder; statements are separated by a line holding only `-- go`. A file is applied once, as one
transaction (it either all lands or nothing does), and its version is recorded in review.schema_migrations by the file itself. `status` only reads.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import neon_http  # noqa: E402

SPLIT = re.compile(r"^-- go\s*$", re.MULTILINE)


def split_statements(text: str) -> list[str]:
    """The statements of a migration file, comments-only chunks dropped."""
    out = []
    for chunk in SPLIT.split(text):
        body = "\n".join(line for line in chunk.splitlines() if line.strip() and not line.strip().startswith("--")).strip()
        if body:
            out.append(chunk.strip())
    return out


def migration_files() -> list[Path]:
    return sorted(p for p in HERE.glob("[0-9][0-9][0-9]_*.sql"))


def applied(url: str) -> set[str]:
    exists = neon_http.run(url, ["select to_regclass('review.schema_migrations') as t"])[0][0]["t"]
    if not exists:
        return set()
    return {r["version"] for r in neon_http.run(url, ["select version from review.schema_migrations"])[0]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["status", "apply"])
    ap.add_argument("--env-file")
    a = ap.parse_args(argv)
    url = neon_http.read_url(a.env_file)
    done = applied(url)
    pending = [p for p in migration_files() if p.stem not in done]
    print("applied:", sorted(done) or "none", "| pending:", [p.stem for p in pending] or "none")
    if a.command == "status":
        return 0
    for p in pending:
        statements = split_statements(p.read_text(encoding="utf-8"))
        try:
            neon_http.run(url, statements)
        except neon_http.NeonError as e:
            print(f"{p.stem}: REFUSED, nothing applied: {e.message}")
            return 1
        print(f"{p.stem}: applied ({len(statements)} statements, one transaction)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
