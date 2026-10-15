"""The silver table definitions are generated from the contract; these tests keep the two in step with the transform."""
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, schema, transform  # noqa: E402

C = contract.load()
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bronze_records.jsonl"
LINEAGE = {"source_file": "f.json.gz", "file_sha256": "ab" * 32, "bronze_ingested_at": "2026-10-14T09:00:00",
           "silver_processed_at": "2026-10-14T09:05:00", "job_run_id": "t"}


def ddl_columns(sql: str) -> dict:
    body = sql[sql.index("(\n") + 2: sql.rindex("\n)")]
    out = {}
    for line in body.split(",\n"):
        name, _, rest = line.strip().partition(" ")
        out[name] = rest
    return out


def test_type_mapping():
    assert schema.spark_type("string") == "STRING" and schema.spark_type("bigint") == "BIGINT"
    assert schema.spark_type("array<string>") == "ARRAY<STRING>"
    assert schema.spark_type("map<string,struct<value:double,unit:string,modifier:string>>") == \
        "MAP<STRING,STRUCT<value:DOUBLE,unit:STRING,modifier:STRING>>"


def test_every_contract_column_is_in_the_ddl_in_order_with_the_right_nullability():
    cols = ddl_columns(schema.silver_table_sql(C))
    assert list(cols) == [c["name"] for c in C["columns"]]
    for c in C["columns"]:
        assert cols[c["name"]].endswith("NOT NULL") == (not c["nullable"]), c["name"]
        assert cols[c["name"]].removesuffix(" NOT NULL") == schema.spark_type(c["type"]), c["name"]


def test_nested_types_are_balanced_and_complete():
    cols = ddl_columns(schema.silver_table_sql(C))
    for name in ("nutrients", "input_sets"):
        assert cols[name].count("<") == cols[name].count(">")
    assert cols["input_sets"].startswith("ARRAY<STRUCT<source:STRING,per:STRING,per_quantity:DOUBLE,per_unit:STRING,preparation:STRING,nutrients:MAP<")


def test_ddl_matches_what_the_transform_produces():
    cols = set(ddl_columns(schema.silver_table_sql(C)))
    seen = 0
    for line in open(FIXTURES, encoding="utf-8"):
        r = transform.process(json.loads(line)["raw_json"], transform.Context(C, "k" * 32), LINEAGE)
        if r.kind == "silver":
            assert set(r.row) == cols
            seen += 1
    assert seen >= 15


def test_five_tables_named_from_the_contract_and_no_identity_table():
    sql = schema.all_table_sql(C)
    assert len(sql) == 5
    for name, s in zip((C["table"], C["quarantine_table"], C["manifest_table"], C["stats_table"], C["field_log_table"]), sql):
        assert f"CREATE TABLE IF NOT EXISTS {name} (" in s and s.endswith("USING DELTA")
    assert not any("identity" in s for s in sql)


def test_quarantine_table_holds_what_the_batch_returns_and_nothing_about_personal_data_columns():
    q = ddl_columns(schema.quarantine_table_sql(C))
    assert set(q) == {"code", "last_modified_t", "reason", "payload", "source_file", "file_sha256", "record_sha256",
                      "bronze_ingested_at", "quarantined_at", "job_run_id", "resolved_by_run"}
    assert q["reason"].endswith("NOT NULL") and "NOT NULL" not in q["code"]      # a broken record may have no code


def test_run_stats_table_records_what_the_checks_did():
    cols = ddl_columns(schema.stats_table_sql(C))
    for needed in ("rows_in", "rows_silver", "rows_quarantine", "quarantine_by_reason", "coerce_failures", "nutrition_format",
                   "tags_dropped", "patterns_scrubbed", "own_handles_redacted", "nutrient_entries_dropped", "enums_nulled",
                   "top_level_fields_seen"):
        assert needed in cols, needed
    assert "short_name_hits" not in cols and "identities_added" not in cols


def test_struct_ddl_is_the_column_list_without_not_null():
    ddl = schema.struct_ddl(C)
    assert "NOT NULL" not in ddl and ddl.startswith("code STRING, code_kind STRING") and ddl.count(", ") >= 70


def test_relocated_contract_moves_every_table():
    moved = contract.relocate(C, silver_schema="workspace.scratch_s", bronze_schema="workspace.scratch_b")
    for sql in schema.all_table_sql(moved):
        assert "packsense_silver" not in sql
    assert re.search(r"^CREATE TABLE IF NOT EXISTS workspace\.scratch_s\.silver_product_versions \(", schema.silver_table_sql(moved))


def test_no_tabs_or_unbalanced_brackets_in_any_ddl():
    for s in schema.all_table_sql(C):
        assert "\t" not in s and s.count("(") == s.count(")") and s.count("<") == s.count(">")
