"""The ten columns contract v4 added, on real OFF records (all three fixture files), plus the guarantee that adding them changed nothing else.

Real values come from the fixtures (bronze_records.jsonl, seed_india_lines.jsonl, seed_india_legacy.jsonl). Edge cases are made the way
the other tests make them: one field of a real record is changed.
"""
import copy
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, transform  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
LINEAGE = {"source_file": "openfoodfacts_products_1791094877_1791181482.json.gz", "file_sha256": "ab" * 32,
           "bronze_ingested_at": "2026-10-14T09:00:00", "silver_processed_at": "2026-10-14T09:05:00", "job_run_id": "test-run"}
C = contract.load()
CTX = transform.Context(C, KEY)
TAG = re.compile(C["shape"]["tag"])
LONG_DIGITS = re.compile(r"\d{7,}")
TAG_COLUMNS = ["additives_tags", "ingredients_analysis_tags", "nutrient_levels_tags", "food_groups_tags", "packaging_tags", "origins_tags"]
NEW_COLUMNS = TAG_COLUMNS + ["product_quantity_unit", "environmental_score_grade", "checked", "last_checked_t"]


def load(name):
    out = []
    for line in (FIX / name).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            out.append((rec["case"], json.loads(rec["raw_json"])))
    return out


REAL = load("bronze_records.jsonl") + load("seed_india_lines.jsonl") + load("seed_india_legacy.jsonl")
REAL_OK = [(c, d) for c, d in REAL if c != "non_digit_code"]       # the empty barcode is quarantined by design


def go(d):
    return transform.process(json.dumps(d, ensure_ascii=False), CTX, LINEAGE)


def with_field(**changes):
    case, d = next((c, x) for c, x in REAL_OK if c == "normal_new")
    d = copy.deepcopy(d)
    d.update(changes)
    return go(d)


# ---- the contract itself -------------------------------------------------------------------------------------------------

def test_the_ten_new_columns_are_in_the_contract_with_the_declared_kinds():
    by = {c["name"]: c for c in C["columns"]}
    assert all(n in by for n in NEW_COLUMNS) and len(NEW_COLUMNS) == 10
    for n in TAG_COLUMNS:
        assert by[n]["type"] == "array<string>" and by[n]["tag_check"] == "shape" and by[n]["class"] == "public" and by[n]["nullable"]
    for n in ("product_quantity_unit", "environmental_score_grade", "checked"):
        assert by[n]["type"] == "string" and by[n]["shape_check"] == "enum" and by[n]["class"] == "public"
    assert by["last_checked_t"]["type"] == "bigint"
    assert not any(by[n].get("egress") for n in NEW_COLUMNS)
    assert all(by[n]["max_digit_run"] == 6 for n in TAG_COLUMNS)
    assert not any("max_digit_run" in c for c in C["columns"] if c["name"] not in TAG_COLUMNS)      # the older tag columns are unchanged


def test_the_fixtures_exercise_every_new_column_with_a_real_value():
    """Otherwise the checks below could pass on nothing."""
    for n in NEW_COLUMNS:
        got = [d[n] for _, d in REAL_OK if d.get(n) not in (None, "", [])]
        assert got, f"no real fixture record carries a non-empty {n}"


# ---- real values come through ---------------------------------------------------------------------------------------------

def test_every_real_record_keeps_exactly_its_well_formed_tags():
    for case, d in REAL_OK:
        row = go(d).row
        for n in TAG_COLUMNS:
            raw = d.get(n)
            if raw is None:
                assert row[n] is None, (case, n)
            else:
                assert row[n] == [t for t in raw if TAG.match(t) and not LONG_DIGITS.search(t)], (case, n)


def test_real_strings_and_numbers_come_through():
    for case, d in REAL_OK:
        row = go(d).row
        for n in ("product_quantity_unit", "environmental_score_grade", "checked"):
            assert row[n] == d.get(n), (case, n)
        lc = d.get("last_checked_t")
        assert row["last_checked_t"] == (int(lc) if lc is not None else None), case


def test_checked_marker_of_the_one_real_checked_product():
    case, d = next((c, x) for c, x in REAL_OK if x.get("checked") == "on")
    row = go(d).row
    assert row["checked"] == "on" and row["last_checked_t"] == int(d["last_checked_t"])
    assert isinstance(d["last_checked_t"], int) and isinstance(row["last_checked_t"], int)    # a text value is covered by the planted test below


def test_absent_fields_stay_null_and_are_not_invented():
    case, d = next((c, x) for c, x in REAL_OK if "checked" not in x)
    row = go(d).row
    assert row["checked"] is None and row["last_checked_t"] is None


# ---- the shape check and the scrub treat the new tag columns like the old ones -------------------------------------------

def test_a_free_text_tag_is_dropped_and_counted_per_column():
    r = with_field(origins_tags=["en:india", "fr:made in india", "de:Käse"])
    assert r.row["origins_tags"] == ["en:india", "de:Käse"]
    assert r.tags_dropped["origins_tags"] == 1


def test_a_bare_domain_inside_a_well_formed_tag_is_scrubbed():
    r = with_field(packaging_tags=["en:www.example.com", "fr:sachet-alu"])
    assert r.row["packaging_tags"][1] == "fr:sachet-alu"
    assert "example.com" not in json.dumps(r.row["packaging_tags"]) and r.scrubbed >= 1


def test_every_new_tag_column_is_checked_and_not_only_origins():
    for n in TAG_COLUMNS:
        r = with_field(**{n: ["en:fine", "not a tag", "x:y z"]})
        assert r.row[n] == ["en:fine"] and r.tags_dropped[n] == 2, n


def test_a_tag_with_a_long_digit_run_is_dropped_in_the_new_columns_only():
    for n in TAG_COLUMNS:
        r = with_field(**{n: ["en:fine", "fr:9876543210", "fr:sachet-12345678-carton", "fr:code-123456"]})
        assert r.row[n] == ["en:fine", "fr:code-123456"], n                  # 6 digits stay, 7 or more go
        assert r.tags_dropped[n] == 2, n
    r = with_field(categories_tags=["en:fine", "fr:9876543210"])             # an older tag column keeps its value (unchanged on purpose)
    assert r.row["categories_tags"] == ["en:fine", "fr:9876543210"]


def test_the_digit_run_option_is_validated():
    bad = copy.deepcopy(C)
    next(x for x in bad["columns"] if x["name"] == "product_name")["max_digit_run"] = 6        # not a tag column
    with pytest.raises(ValueError, match="max_digit_run"):
        contract.validate(bad)
    bad = copy.deepcopy(C)
    next(x for x in bad["columns"] if x["name"] == "packaging_tags")["max_digit_run"] = 0
    with pytest.raises(ValueError, match="max_digit_run"):
        contract.validate(bad)


def test_a_non_list_tag_value_becomes_null_and_is_counted():
    r = with_field(additives_tags="en:e412")
    assert r.row["additives_tags"] is None and r.coerce_failures["additives_tags"] == 1


# ---- strings, numbers ---------------------------------------------------------------------------------------------------

def test_enum_columns_accept_real_grades_and_null_what_does_not_fit():
    for good in ("a", "a-plus", "f", "unknown", "not-applicable"):
        assert with_field(environmental_score_grade=good).row["environmental_score_grade"] == good
    r = with_field(environmental_score_grade="A+ (best)", checked="ON!!", product_quantity_unit="grams and more characters")
    assert r.row["environmental_score_grade"] is None and r.row["checked"] is None and r.row["product_quantity_unit"] is None
    assert r.enums_nulled == 3


def test_last_checked_t_accepts_text_and_numbers_and_rejects_junk():
    assert with_field(last_checked_t="1682349504").row["last_checked_t"] == 1682349504
    assert with_field(last_checked_t=1682349504).row["last_checked_t"] == 1682349504
    r = with_field(last_checked_t="yesterday")
    assert r.row["last_checked_t"] is None and r.coerce_failures["last_checked_t"] == 1


# ---- nothing else moved --------------------------------------------------------------------------------------------------

def test_adding_the_columns_changed_no_other_value_on_any_real_record():
    """The same records through a context whose contract lacks the ten columns: every shared column is identical, so the new columns
    cannot have altered an old one (and the v3 shape of the table is exactly the old columns)."""
    old = copy.deepcopy(C)
    old["columns"] = [c for c in old["columns"] if c["name"] not in NEW_COLUMNS]
    assert len(old["columns"]) == 71
    ctx_old = transform.Context(old, KEY)
    for case, d in REAL:
        raw = json.dumps(d, ensure_ascii=False)
        new_r = transform.process(raw, CTX, LINEAGE)
        old_r = transform.process(raw, ctx_old, LINEAGE)
        assert new_r.kind == old_r.kind and new_r.reason == old_r.reason, case
        if new_r.kind == "silver":
            for name, value in old_r.row.items():
                if name != "silver_contract_version":
                    assert new_r.row[name] == value, (case, name)
            assert set(new_r.row) - set(old_r.row) == set(NEW_COLUMNS), case


def test_a_quarantined_record_carries_the_new_fields_scrubbed():
    case, d = next((c, x) for c, x in REAL if c == "non_digit_code")
    d = copy.deepcopy(d)
    d["packaging_tags"] = ["en:www.example.com"]
    d["checked"] = "on"
    r = go(d)
    assert r.kind == "quarantine" and r.reason == "Q_BAD_CODE"
    payload = json.loads(r.payload)
    assert payload["checked"] == "on" and "example.com" not in json.dumps(payload["packaging_tags"])
