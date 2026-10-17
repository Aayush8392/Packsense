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


def test_committed_fixture_matches_its_manifest():
    manifest = json.loads((FIXTURE.parent / "manifest.json").read_text(encoding="utf-8"))
    rows = fixture_rows()
    assert len(rows) == manifest["version_rows"]
    assert len({r["code"] for r in rows}) == manifest["products"]
    assert set(rows[0]) == set(manifest["columns"])
    assert not any(c.endswith("_hmac") for c in manifest["columns"]), "a hashed column name in the fixture's columns"


# ---- the taxonomy half of the fixture ------------------------------------------------------------------------------------------

TAX_NOTEBOOK = ROOT / "p4_modelling" / "notebooks" / "export_taxonomy_fixture.py"
TAX_FIXTURE = ROOT / "p4_modelling" / "fixtures" / "taxonomy_tag.jsonl"
TAX_MANIFEST = ROOT / "p4_modelling" / "fixtures" / "taxonomy_manifest.json"


def tax_notebook_code():
    return "\n".join(line for line in TAX_NOTEBOOK.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#"))


def test_taxonomy_notebook_calls_the_vocabulary_exit_before_writing_anything():
    code = tax_notebook_code()
    call = code.find("egress.prepare_vocabulary_for_export(")
    assert call != -1, "the taxonomy export notebook must call egress.prepare_vocabulary_for_export"
    # write-mode opens only: the notebook also READS the committed fixture and dbt_project.yml before the exit, which is fine
    writes = [m.start() for m in re.finditer(r'open\([^\n]*"w"|\.write\(|json\.dump\(', code)]
    assert writes and min(writes) > call, "something is written before the exit function has run"


def test_taxonomy_notebook_writes_only_the_cleaned_rows():
    code = tax_notebook_code()
    assert re.search(r"for r in sorted\(clean,", code)
    assert not re.search(r"for r in sorted\(rows,", code)


def test_every_taxonomy_gold_uses_has_a_product_column_in_the_export_notebook():
    import yaml
    used = yaml.safe_load((ROOT / "p4_modelling" / "dbt_project.yml").read_text(encoding="utf-8"))["vars"]["gold_taxonomies"]
    for name in used:
        assert f'"{name}":' in TAX_NOTEBOOK.read_text(encoding="utf-8"), f"export_taxonomy_fixture.py has no USED_BY entry for {name}"


def test_committed_taxonomy_fixture_is_clean_and_matches_its_manifest():
    manifest = json.loads(TAX_MANIFEST.read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in TAX_FIXTURE.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == manifest["version_rows"] and set(rows[0]) == set(manifest["columns"])
    patterns = personal.compile_patterns(C)
    replacement = C["scrub"]["replacement"]
    for row in rows:
        assert not (egress.never_columns(C) & set(row))
        for text in egress._all_strings(list(row.values())):
            assert not personal.has_pattern(text.replace(replacement, ""), patterns), f"scrub pattern left in {row['taxonomy']} {row['tag']}"
    assert not any(k in manifest["columns"] for k in ("loaded_at", "job_run_id")), "run-specific lineage columns must stay out of the fixture"
