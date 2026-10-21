"""p6_serving/export_lib.py on real rows of the DuckDB fixture build (tests/fixtures/gold_rows.json): the column rule, the exit function,
small-number suppression, deterministic files, and the licence gate as the last step."""
import copy
import csv
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
SPEC = ex.load_spec()
STATUS = {"built_at_utc": "2026-10-21T08:30:00", "first_complete_day": "2026-10-01",
          "last_complete_day": "2026-10-15", "products_held_all": 233, "products_held_india": 60}


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
    assert names == ["ATTRIBUTION.md", "brand_scorecard.csv", "change_daily.csv", "pipeline_health.csv", "quality_daily.csv", "site_status.csv"]
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
