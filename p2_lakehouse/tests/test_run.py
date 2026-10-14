"""Batch processing: the two-pass identity step, the balance check and the shape of what the notebook writes.

Rows are real bronze records (see fixtures/README.md); the bronze columns the notebook reads are rebuilt from the record.
"""
import copy
import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, run, schema, transform  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
C = contract.load()
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bronze_records.jsonl"
NOW = dt.datetime(2026, 10, 14, 9, 5)


def bronze_row(raw: str, source_file="openfoodfacts_products_1791094877_1791181482.json.gz"):
    try:
        d = json.loads(raw)
        code, lmt = d.get("code"), d.get("last_modified_t")
    except Exception:
        code, lmt = None, None
    return {"code": code, "last_modified_t": lmt, "raw_json": raw, "source_file": source_file,
            "file_sha256": "ab" * 32, "ingested_at": dt.datetime(2026, 10, 14, 9, 0)}


def all_rows():
    return [bronze_row(json.loads(line)["raw_json"]) for line in open(FIXTURES, encoding="utf-8")]


def case(name, i=0):
    seen = 0
    for line in open(FIXTURES, encoding="utf-8"):
        rec = json.loads(line)
        if rec["case"] == name:
            if seen == i:
                return rec["raw_json"]
            seen += 1
    raise KeyError(name)


def columns_of(sql: str) -> set:
    body = sql[sql.index("(\n") + 2: sql.rindex("\n)")]
    return {line.strip().split(" ")[0] for line in body.split(",\n")}


def fresh_ctx():
    return transform.Context(C, KEY)


def test_every_row_is_in_silver_or_quarantine_and_nothing_else():
    rows = all_rows()
    res = run.process_batch(rows, fresh_ctx(), "run-1", NOW)
    assert res.balanced() and res.rows_in == len(rows) == len(res.silver) + len(res.quarantine)
    assert len(res.quarantine) == 1 and res.reasons == {"Q_BAD_CODE": 1}
    assert res.nutrition_format["new"] > 0 and res.nutrition_format["none"] > 0


def test_what_the_notebook_writes_has_exactly_the_tables_columns():
    res = run.process_batch(all_rows(), fresh_ctx(), "run-1", NOW)
    assert all(set(r) == columns_of(schema.silver_table_sql(C)) for r in res.silver)
    assert all(set(r) == columns_of(schema.quarantine_table_sql(C)) for r in res.quarantine)


def test_quarantine_rows_carry_a_record_hash_a_reason_and_no_username():
    res = run.process_batch(all_rows(), fresh_ctx(), "run-1", NOW)
    q = res.quarantine[0]
    assert re.fullmatch(r"[0-9a-f]{64}", q["record_sha256"]) and q["reason"] == "Q_BAD_CODE"
    assert q["resolved_by_run"] is None and q["quarantined_at"] == NOW and q["job_run_id"] == "run-1"
    assert "user_0" not in (q["payload"] or "")


def test_a_name_from_another_record_in_the_same_batch_is_caught_in_any_order():
    a = json.loads(case("normal_new"))
    b = json.loads(case("gtin8"))
    # b's product name carries a's creator: unknown to the (empty) identity table, known only through the batch
    b["product_name"] = f"Biscuits by {a['creator']}"
    rows = [bronze_row(json.dumps(a)), bronze_row(json.dumps(b))]
    for order in (rows, rows[::-1]):
        res = run.process_batch(order, fresh_ctx(), "run-1", NOW)
        assert [q["reason"] for q in res.quarantine] == ["Q_PII_FOUND"]
        assert res.quarantine[0]["pii_columns"] == ["product_name"] and res.balanced()


def test_known_identities_are_returned_and_added_to_the_context():
    ctx = fresh_ctx()
    res = run.process_batch(all_rows(), ctx, "run-1", NOW)
    assert res.users and all(len(h) == 64 for h in res.users)
    assert set(res.users) <= ctx.known_users and set(res.phones) <= ctx.known_phones
    assert res.phones, "the fixtures include a record with a phone number in a customer-service field"


def test_processing_a_batch_twice_gives_the_same_result():
    a = run.process_batch(all_rows(), fresh_ctx(), "run-1", NOW)
    b = run.process_batch(all_rows(), fresh_ctx(), "run-1", NOW)
    assert a.silver == b.silver and a.quarantine == b.quarantine and a.users == b.users


def test_top_level_fields_are_counted_for_the_drift_monitor():
    ctx = fresh_ctx()
    rows = all_rows()
    run.process_batch(rows, ctx, "run-1", NOW)
    assert ctx.field_counts["code"] == len(rows)                       # every record has a code key (one is empty)
    assert "images" not in ctx.field_counts                           # removed from the fixtures on purpose
    assert "product_name" in ctx.field_counts and len(ctx.field_counts) > 300


def test_an_empty_batch_is_balanced_and_harmless():
    res = run.process_batch([], fresh_ctx(), "run-1", NOW)
    assert res.balanced() and res.rows_in == 0 and not res.silver and not res.quarantine


def test_unparseable_rows_are_quarantined_with_distinct_hashes_and_the_same_hash_for_the_same_text():
    rows = [bronze_row("{"), bronze_row("not json"), bronze_row("{")]
    res = run.process_batch(rows, fresh_ctx(), "run-1", NOW)
    assert [q["reason"] for q in res.quarantine] == ["Q_BAD_JSON"] * 3 and res.balanced()
    hashes = [q["record_sha256"] for q in res.quarantine]
    assert hashes[0] == hashes[2] != hashes[1]
    assert all(q["code"] is None for q in res.quarantine)


def test_the_bronze_code_is_kept_when_the_record_itself_has_none():
    d = json.loads(case("normal_new"))
    d.pop("last_modified_t")
    row = bronze_row(json.dumps(d))
    row["last_modified_t"] = 1791254632            # what bronze extracted
    res = run.process_batch([row], fresh_ctx(), "run-1", NOW)
    assert res.quarantine[0]["reason"] == "Q_BAD_LAST_MODIFIED" and res.quarantine[0]["last_modified_t"] == 1791254632


def test_stats_counters_add_up():
    res = run.process_batch(all_rows(), fresh_ctx(), "run-1", NOW)
    assert sum(res.nutrition_format.values()) == len(res.silver)
    assert res.scrubbed >= 1 and res.exempt_hits >= 0 and res.short_hits >= 0
