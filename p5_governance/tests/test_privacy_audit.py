"""Tests for the privacy audit: the SQL is built from the contract and holds no value, the stored result holds nothing but counts, the report is current, and
the measured result still agrees with what the pipeline promises (nothing with a clear contact shape survives the scrub)."""
import copy
import json
import re
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
P5 = ROOT / "p5_governance"
sys.path.insert(0, str(P5))
import privacy_audit_lib as pal  # noqa: E402

T = pal.tables()
RES = pal.load_result()
CONTRACT = yaml.safe_load((ROOT / "p2_lakehouse" / "contracts" / "silver.yml").read_text(encoding="utf-8"))


def test_the_stored_result_holds_nothing_but_counts_a_date_and_labels():
    assert pal.only_counts(RES) == []


@pytest.mark.parametrize("bad", [
    {"known_names": {"8_plus": {"bronze": {"name": "someone"}}}},
    {"rows": {"bronze_rows": 1.5}},
    {"tags_dropped": {"Some Name": 3}},
    {"rows": {"bronze_rows": True}},
])
def test_a_result_with_a_string_a_float_or_a_name_like_key_is_refused(bad):
    assert pal.only_counts({**RES, **bad}) != []


def test_the_generated_report_is_current():
    assert pal.DOC_PATH.read_text(encoding="utf-8") == pal.render(RES), "PRIVACY_AUDIT.md is stale: python p5_governance/bootstrap/render_privacy_audit.py"


def test_the_patterns_measured_are_exactly_the_contracts_scrub_patterns():
    assert set(T["patterns"]) == set(pal.PATTERNS)
    assert T["patterns"] == {n: CONTRACT["scrub"][n] for n in pal.PATTERNS}
    sql = pal.pattern_counts_sql(T, "silver")
    for rx in T["patterns"].values():
        assert f"r'{rx}'" in sql


def test_the_sql_holds_no_value_only_table_and_field_names_and_patterns():
    for sql in (pal.rows_sql(T), pal.pattern_counts_sql(T, "bronze"), pal.pattern_counts_sql(T, "silver"), pal.pattern_counts_sql(T, "quarantine"),
                pal.known_names_sql(T), pal.tags_dropped_sql(T)):
        assert "SELECT" in sql and not re.search(r"(?i)dapi|token|password|secret", sql)


def test_the_known_name_query_reads_every_personal_source_field_of_the_contract_that_silver_hashes():
    sql = pal.known_names_sql(T)
    for f in (*pal.SCALAR_FIELDS, *pal.ARRAY_FIELDS):
        assert f"$.{f}" in sql
    hashed_sources = {c["from"].removeprefix("$.") for c in CONTRACT["columns"] if c.get("class") == "hashed"}
    assert hashed_sources <= {*pal.SCALAR_FIELDS, *pal.ARRAY_FIELDS}, "a hashed source field is not in the known-name measurement"


def test_the_name_classes_follow_the_contracts_own_handle_length_and_the_ordinary_rule():
    sql = pal.known_names_sql(T)
    assert f"h.len >= {CONTRACT['own_handle_redaction']['min_length']}" in sql
    assert f"HAVING count(DISTINCT rid) >= {pal.ORDINARY_MIN_PRODUCTS}" in sql
    assert pal.ORDINARY_MIN_PRODUCTS == 10          # the exit function's 'ordinary word' threshold


def test_a_pattern_with_a_single_quote_cannot_become_a_raw_string():
    with pytest.raises(ValueError):
        pal._raw("it's")


def test_measure_shapes_every_answer_into_integers_with_a_fake_warehouse():
    n_pat = lambda cols: ([c for c in cols], [[str(i) for i, _ in enumerate(cols)]])   # noqa: E731
    calls = []

    def run(sql):
        calls.append(sql)
        if "AS bronze_rows" in sql:
            return ["bronze_rows", "silver_rows", "quarantine_rows", "silver_codes"], [["10", "9", "1", "8"]]
        if "AS tok" in sql:
            return [], [["bronze", "8_plus", "2", "1", "3", "4"], ["silver", "8_plus", "1", "1", "2", "4"]]
        if "tags_dropped" in sql:
            return [], [["categories_tags", "5"], ["Bad Key", "1"]]
        cols = ["name__email", "name__any", "brands__any"] + (["name__replacement_marker"] if "LIKE" in sql else [])
        return n_pat(cols)

    res = pal.measure(run, "2026-10-19")
    assert pal.only_counts(res) == []
    assert res["rows"]["bronze_rows"] == 10 and res["known_names"]["8_plus"]["bronze"]["either"] == 3
    assert res["tags_dropped"] == {"categories_tags": 5}        # a key that is not a plain label is dropped
    assert len(calls) == 6


def test_after_the_scrub_nothing_with_a_clear_contact_shape_is_left_in_kept_free_text():
    """The pipeline's promise, re-measured on every audit run: a pattern hit in silver is a defect, not a bound."""
    for col in ("name", "brands"):
        assert RES["patterns"]["silver"][col]["any"] == 0
        for p in pal.PATTERNS:
            assert RES["patterns"]["silver"][col][p] == 0


def test_scrubbing_only_removes_hits_and_the_marker_counts_what_it_removed():
    b, s = RES["patterns"]["bronze"], RES["patterns"]["silver"]
    for col in ("name", "brands"):
        assert s[col]["any"] <= b[col]["any"]
        assert s[col]["replacement_marker"] >= b[col]["any"] - 1        # every raw hit became a marker (a quarantined row may account for one)


def test_the_own_name_redaction_can_only_lower_the_name_count_and_never_adds_brand_hits():
    k = RES["known_names"]["8_plus"]
    assert k["silver"]["name"] <= k["bronze"]["name"]
    assert k["silver"]["brands"] <= k["bronze"]["brands"]


def test_rows_in_the_result_agree_with_each_other():
    r = RES["rows"]
    assert r["silver_rows"] + r["quarantine_rows"] == r["bronze_rows"]
    assert r["silver_codes"] <= r["silver_rows"]


def test_the_report_states_its_limits_in_plain_words():
    text = pal.render(RES)
    for phrase in ("not a guarantee", "Phone numbers are not scrubbed by pattern", "pseudonymised data remains personal data", "counts only", "What was not measured"):
        assert phrase in text
    assert "anonymis" in text and "never claims anonymisation" in text


def test_a_changed_result_changes_the_report():
    changed = copy.deepcopy(RES)
    changed["known_names"]["8_plus"]["silver"]["name"] += 1
    assert pal.render(changed) != pal.render(RES)


def test_the_stored_file_is_valid_json_with_the_expected_top_level_keys():
    raw = json.loads(pal.RESULT_PATH.read_text(encoding="utf-8"))
    assert {"measured_at", "engine", "rows", "patterns", "known_names", "tags_dropped"} <= set(raw)
