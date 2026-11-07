"""p6_serving/export_lib.py on real rows of the DuckDB fixture build (tests/fixtures/gold_rows.json): the column rule, the exit function,
small-number suppression, deterministic files, and the licence gate as the last step."""
import copy
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving"))
import export_lib as ex  # noqa: E402

ROWS = json.loads((HERE / "fixtures" / "gold_rows.json").read_text(encoding="utf-8"))
HEALTH = json.loads((ROOT / "p9_operations" / "tests" / "fixtures" / "health_real.json").read_text(encoding="utf-8"))["rows"]   # real collector output
OFF = json.loads((HERE / "fixtures" / "off_weekly_real.json").read_text(encoding="utf-8"))   # the two whole-OFF tables as production built them (counts only)
SPEC = ex.load_spec()
STATUS = {"built_at_utc": "2026-10-21T08:30:00", "first_complete_day": "2026-10-01",
          "last_complete_day": "2026-10-15", "products_held_all": 233, "products_held_india": 60}


def category_rows():
    """The ranked rows of mart_category_fitness as production built them on 7 Nov 2026 (counts and category tags only), typed."""
    table = json.loads((HERE / "fixtures" / "category_fitness_real.json").read_text(encoding="utf-8"))
    return [{k: (v if k in ("scope", "category", "as_of_date") else int(v)) for k, v in zip(table["columns"], row)} for row in table["rows"]]


def off_rows(name):
    """The real rows of one whole-OFF table with their types back (Spark hands the SDK strings): dates as dates, the severity and kind as text, the rest as integers."""
    table = OFF[name]
    out = []
    for row in table["rows"]:
        rec = dict(zip(table["columns"], row))
        out.append({k: (dt.date.fromisoformat(v) if k in ("week_end", "snapshot_date") else v if k in ("severity", "kind") else int(v)) for k, v in rec.items()})
    return out


def datasets(rank_all_named=True):
    """The fixture's real rows in the shape the notebook delivers. No fixture brand reaches the real floor of 30, so (test only) every named brand is
    treated as ranked; the rows themselves are untouched."""
    out = {}
    for name, rows in ROWS.items():
        cols = SPEC["datasets"][name]["columns"]
        keep = [r for r in rows if (r["is_ranked"] == 1 or (rank_all_named and r["brand_name"] != "(no brand)"))] if name == "brand_scorecard" else rows
        out[name] = [{k: r[k] for k in cols} for r in keep]
    cols = SPEC["datasets"]["pipeline_health"]["columns"]
    out["pipeline_health"] = [{k: r[k] for k in cols} for r in HEALTH]
    for name, table in (("off_weekly", "public_off_weekly"), ("off_open_flags", "public_off_open_flags")):
        out[name] = [{k: r[k] for k in SPEC["datasets"][name]["columns"]} for r in off_rows(table)]
    out["category_fitness"] = category_rows()   # the fixture build has no category with 200 products, so the ranked rows are production's own
    return out


def test_the_spec_loads_and_exports_only_public_columns():
    assert ex.classification_problems(SPEC) == []


def test_per_brand_error_counts_are_not_exportable():
    cols = SPEC["datasets"]["brand_scorecard"]["columns"]
    assert not {"open_error_spans", "open_warning_spans", "n_products_with_error_flag"} & set(cols)


def test_the_ranking_floor_keeps_the_exit_functions_premise_true():
    import yaml
    floor = yaml.safe_load((ROOT / "p4_modelling" / "dbt_project.yml").read_text(encoding="utf-8"))["vars"]["scorecard_min_products"]
    contract = ex.silver_contract.load()
    assert floor >= contract["egress"]["ordinary_word_min_products"]


def test_select_sql_names_its_columns_and_never_star():
    for name in SPEC["datasets"]:
        sql = ex.select_sql(name, SPEC, "workspace.packsense_gold")
        home = SPEC["datasets"][name].get("schema") or "workspace.packsense_gold"
        assert "*" not in sql and sql.startswith("select ") and f" from {home}." in sql
    assert "where is_ranked = 1" in ex.select_sql("brand_scorecard", SPEC, "s")


def test_a_row_with_an_extra_or_missing_column_is_refused():
    rows = datasets()["change_daily"]
    extra = [dict(rows[0], hidden=1)] + rows[1:]
    with pytest.raises(ex.ExportRefused):
        ex.build_dataset("change_daily", extra, SPEC)
    short = [{k: v for k, v in rows[0].items() if k != "n_periods"}]
    with pytest.raises(ex.ExportRefused):
        ex.build_dataset("change_daily", short, SPEC)


def test_counts_of_one_to_four_are_blanked_and_counted_and_nothing_else_changes():
    rows = datasets()["quality_daily"]
    out, rep = ex.build_dataset("quality_daily", rows, SPEC)
    cols = SPEC["datasets"]["quality_daily"]["count_columns"]
    expected = sum(1 for r in rows for c in cols if r[c] is not None and 0 < r[c] < 5)
    assert expected > 0 and rep["suppressed_cells"] == expected
    assert all(r[c] is None or r[c] == 0 or r[c] >= 5 for r in out for c in cols)
    assert sum(1 for r in out for c in cols if r[c] is None) == expected
    assert len(out) == len(rows)
    # a column that is not a listed count column is never touched
    assert sorted(r["n_products_held"] for r in out) == sorted(r["n_products_held"] for r in rows)


def test_the_exit_function_scrubs_a_contact_planted_in_a_brand_name():
    rows = copy.deepcopy(datasets()["brand_scorecard"])
    rows[0]["brand_name"] = "someshop contact boss@example.com"
    out, rep = ex.build_dataset("brand_scorecard", rows, SPEC)
    assert all("@" not in r["brand_name"] for r in out)
    assert rep["patterns_removed"] >= 1


def test_the_release_folder_passes_the_gate_and_the_files_are_deterministic(tmp_path):
    m1 = ex.build_release(tmp_path / "a", datasets(), STATUS)
    m2 = ex.build_release(tmp_path / "b", datasets(), STATUS)
    assert [f["sha256"] for f in m1["files"]] == [f["sha256"] for f in m2["files"]]
    names = sorted(f["path"] for f in m1["files"])
    assert names == ["ATTRIBUTION.md", "brand_scorecard.csv", "category_fitness.csv", "change_daily.csv", "nutrition_sources.csv", "off_open_flags.csv", "off_weekly.csv", "pipeline_health.csv", "quality_daily.csv", "rule_checks.csv", "site_status.csv"]
    with open(tmp_path / "a" / "brand_scorecard.csv", encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    assert header == SPEC["datasets"]["brand_scorecard"]["columns"]
    assert b"\r" not in (tmp_path / "a" / "quality_daily.csv").read_bytes()
    assert json.loads((tmp_path / "a" / ex.MANIFEST).read_text(encoding="utf-8"))["exit_function"]["called"] is True


def test_the_exit_scrubs_a_url_and_the_gate_stops_an_image_the_exit_does_not_see(tmp_path):
    ds = copy.deepcopy(datasets())
    ds["quality_daily"][0]["flag_family"] = "https://images.openfoodfacts.org/images/products/1.jpg"   # a text column: the exit replaces the URL
    ex.build_release(tmp_path / "scrubbed", ds, STATUS)
    assert "images.openfoodfacts" not in (tmp_path / "scrubbed" / "quality_daily.csv").read_text(encoding="utf-8")
    ds = copy.deepcopy(datasets())
    ds["quality_daily"][0]["scope"] = "photo.jpg"   # a column the exit does not read: only the gate can catch it
    with pytest.raises(ex.ExportRefused, match="licence gate"):
        ex.build_release(tmp_path / "bad", ds, STATUS)


def test_the_gate_stops_a_future_dump_date(tmp_path):
    with pytest.raises(ex.ExportRefused, match="future"):
        ex.build_release(tmp_path / "future", datasets(), dict(STATUS, last_complete_day="2999-01-01"))


def test_a_dataset_that_was_not_provided_is_refused(tmp_path):
    ds = datasets()
    del ds["change_daily"]
    with pytest.raises(ex.ExportRefused):
        ex.build_release(tmp_path / "missing", ds, STATUS)


def test_no_exported_text_matches_a_scrub_pattern(tmp_path):
    ex.build_release(tmp_path / "ok", datasets(), STATUS)
    text = "\n".join(p.read_text(encoding="utf-8") for p in (tmp_path / "ok").glob("*.csv"))
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)


# --- the two whole-OFF datasets ('Across all of OFF'), on the rows production built (tests/fixtures/off_weekly_real.json) -----------------------------

def test_the_whole_off_tables_are_exactly_what_the_snapshot_library_defines():
    sys.path.insert(0, str(ROOT / "p9_operations"))
    import snapshot_lib as lib
    d = lib.ddl("workspace.packsense_snapshots")
    for dataset, table in (("off_weekly", "public_off_weekly"), ("off_open_flags", "public_off_open_flags")):
        assert SPEC["datasets"][dataset]["schema"] == "workspace.packsense_snapshots" and SPEC["datasets"][dataset]["table"] == table
        assert SPEC["datasets"][dataset]["columns"] == lib.ddl_columns(d[table])          # every column, in the table's order
        assert OFF[table]["columns"] == lib.ddl_columns(d[table])


def test_the_whole_off_files_hold_counts_only_and_lose_nothing_to_blanking():
    for dataset, table in (("off_weekly", "public_off_weekly"), ("off_open_flags", "public_off_open_flags")):
        rows = [{k: r[k] for k in SPEC["datasets"][dataset]["columns"]} for r in off_rows(table)]
        out, rep = ex.build_dataset(dataset, rows, SPEC)
        assert len(out) == len(rows) and rep["suppressed_cells"] == 0         # every real cell is far above the blanking floor
        assert not any("@" in str(r.get("kind", "")) for r in out)


def test_the_open_flags_of_the_newest_snapshot_equal_the_flags_the_triage_scoring_recorded_for_it():
    rows = off_rows("public_off_open_flags")
    newest = max(r["snapshot_date"] for r in rows)
    assert newest == dt.date(2026, 11, 1)
    errors = sum(r["open_flags"] for r in rows if r["snapshot_date"] == newest and r["severity"] == "error")
    assert errors == 261_383                                                      # the scoring wrote 261,383 error flags for this snapshot (item 20)


def test_the_open_flags_file_stays_small_whatever_kinds_OFF_adds():
    rows = off_rows("public_off_open_flags")
    per_day = {}
    for r in rows:
        per_day.setdefault(r["snapshot_date"], set()).add((r["severity"], r["kind"]))
    assert len(per_day) == 33 and max(len(v) for v in per_day.values()) <= 40 + 3
    assert {r["severity"] for r in rows} == {"error", "warning", "info"}
    assert len(rows) == 1419


def test_the_weekly_file_has_one_row_per_week_ending_on_a_snapshot():
    rows = off_rows("public_off_weekly")
    ends = sorted(r["week_end"] for r in rows)
    assert len(set(ends)) == 32 and ends[0] == dt.date(2026, 3, 29) and ends[-1] == dt.date(2026, 11, 1)
    assert all(6 <= (b - a).days <= 8 for a, b in zip(ends, ends[1:]))           # weekly, but OFF's snapshots are not always exactly 7 days apart (6 and 8 days in July)


# --- the three datasets behind the chart gallery (real rows of the DuckDB fixture build) ---------------------------------------------------------------

def test_the_rule_checks_name_exactly_the_eleven_rules_for_each_scope_and_never_flag_more_than_they_check():
    sys.path.insert(0, str(ROOT / "p7_triage_ml"))
    import rules_lib
    rows = ROWS["rule_checks"]
    for scope in ("all", "india"):
        assert {r["rule"] for r in rows if r["scope"] == scope} == set(rules_lib.RULES)
    assert all(0 <= r["n_products_flagged"] <= r["n_products_checked"] for r in rows)
    assert "n_products_flagged" in SPEC["datasets"]["rule_checks"]["columns"] and "code" not in SPEC["datasets"]["rule_checks"]["columns"]


def test_the_nutrition_sources_hold_sets_and_products_and_a_source_never_has_more_products_than_sets():
    rows = ROWS["nutrition_sources"]
    assert {r["source"] for r in rows if r["scope"] == "all"} >= {"packaging", "estimate"}
    assert all(1 <= r["n_products"] <= r["n_sets"] for r in rows)
    assert not {"code", "barcode"} & set(SPEC["datasets"]["nutrition_sources"]["columns"])


def test_the_category_file_is_ranked_categories_only_and_leaves_out_the_28_day_artefact():
    spec = SPEC["datasets"]["category_fitness"]
    assert spec["where"] == "is_ranked = 1"
    assert not {"n_changed_28d", "n_stale_365d", "is_ranked"} & set(spec["columns"])
    assert "(no category)" not in {r["category"] for r in ROWS["category_fitness"] if r["is_ranked"] == 1}


def test_the_gallery_files_pass_the_exit_function_and_the_blanking_is_counted(tmp_path):
    m = ex.build_release(tmp_path / "r", datasets(), STATUS)
    paths = {f["path"] for f in m["files"]}
    assert {"category_fitness.csv", "rule_checks.csv", "nutrition_sources.csv"} <= paths


def test_the_real_ranked_categories_are_big_public_counts_that_blanking_leaves_alone():
    rows = category_rows()
    assert len(rows) == 29 and {r["scope"] for r in rows} == {"all", "india"}
    assert all(r["n_products"] >= 200 for r in rows) and all(r["category"] != "(no category)" for r in rows)
    out, rep = ex.build_dataset("category_fitness", rows, SPEC)
    assert rep["suppressed_cells"] == 0 and len(out) == 29
