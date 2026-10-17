"""The fixture leaves through the exit function, and the committed file proves it.

Three checks:
  1. the export notebook calls `prepare_for_export`, and calls it before anything is written (a path that skips it fails here),
  2. the notebook refuses to run if the staging view carries a column the contract marks `egress: never`,
  3. the committed fixture holds no `egress: never` column, no scrub pattern and no contributor-shaped hash.
"""
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p2_lakehouse"))

from silver_lib import contract, egress, personal  # noqa: E402

NOTEBOOK = ROOT / "p4_modelling" / "notebooks" / "export_fixture.py"
FIXTURE = ROOT / "p4_modelling" / "fixtures" / "stg_silver_versions.jsonl"
C = contract.load()


def notebook_code():
    """The notebook without comment lines, so a mention in a comment cannot satisfy the checks."""
    return "\n".join(line for line in NOTEBOOK.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))


def test_notebook_calls_the_exit_function_before_writing_anything():
    code = notebook_code()
    call = code.find("egress.prepare_for_export(")
    assert call != -1, "the export notebook must call egress.prepare_for_export"
    writes = [m.start() for m in re.finditer(r"open\(|\.write\(|json\.dump\(", code)]
    assert writes, "the guard assumes the notebook writes the file with open()"
    assert min(writes) > call, "something is written before the exit function has run"


def test_notebook_writes_only_the_cleaned_rows():
    code = notebook_code()
    # the file is written from `clean` (the exit function's result), never from `rows` (the raw staging rows)
    assert re.search(r"for r in sorted\(clean,", code)
    assert not re.search(r"for r in sorted\(rows,", code)


def test_notebook_refuses_never_columns_in_the_staging_view():
    assert "egress.never_columns(C)" in notebook_code()
    assert "egress: never" in NOTEBOOK.read_text(encoding="utf-8")


def fixture_rows():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]


@pytest.mark.skipif(not FIXTURE.exists(), reason="the fixture has not been exported yet; remove this skip once it is committed")
def test_committed_fixture_has_no_hashed_columns_and_no_scrub_pattern():
    rows = fixture_rows()
    assert rows
    banned = egress.never_columns(C)
    patterns = personal.compile_patterns(C)
    sentinel, replacement = C["own_handle_redaction"]["sentinel"], C["scrub"]["replacement"]
    for row in rows:
        assert not (banned & set(row)), f"hashed column in the fixture: {sorted(banned & set(row))}"
        for col in contract.text_column_names(C):
            values = row.get(col)
            for text in values if isinstance(values, list) else [values]:
                if isinstance(text, str):
                    body = text.replace(sentinel, "").replace(replacement, "")
                    assert not personal.has_pattern(body, patterns), f"scrub pattern left in {col} of {row['code']}"


@pytest.mark.skipif(not FIXTURE.exists(), reason="the fixture has not been exported yet; remove this skip once it is committed")
def test_committed_fixture_matches_its_manifest():
    manifest = json.loads((FIXTURE.parent / "manifest.json").read_text(encoding="utf-8"))
    rows = fixture_rows()
    assert len(rows) == manifest["version_rows"]
    assert len({r["code"] for r in rows}) == manifest["products"]
    assert set(rows[0]) == set(manifest["columns"])
    assert not any(c.endswith("_hmac") for c in manifest["columns"]), "a hashed column name in the fixture's columns"
