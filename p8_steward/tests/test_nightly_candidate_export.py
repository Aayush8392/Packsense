"""Tests for the nightly candidate export (nightly/candidate_export_lib.py). The rows are plain dicts with digit barcodes: they test the rules, not the data."""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import candidate_export_lib as ce  # noqa: E402
from nightly import line_record as lr  # noqa: E402
from nightly import store as st  # noqa: E402


def row(code, per="100g", **vals):
    base = {"code": code, "nutrition_per": per, "energy_kcal": 90.0, "fat": 0.5, "salt": 0.06}
    base.update(vals)
    return base


def rows(n, start=10000000):
    return [row(str(start + i)) for i in range(n)]


def test_first_export_marks_nobody_new():
    doc, counts = ce.build_document(rows(5), None, "2026-11-14")
    assert doc["exported"] == "2026-11-14"
    assert [c["new"] for c in doc["candidates"]] == [False] * 5
    assert counts["exported"] == 5 and counts["new"] == 0 and counts["previous"] == 0


def test_new_means_not_in_the_previous_export():
    prev, _ = ce.build_document(rows(5), None, "2026-11-13")
    doc, counts = ce.build_document(rows(6), prev, "2026-11-14")
    assert [c["code"] for c in doc["candidates"] if c["new"]] == ["10000005"]
    assert counts["new"] == 1 and counts["previous"] == 5


def test_candidates_are_sorted_and_hold_only_the_known_fields():
    doc, _ = ce.build_document([row("10000002", fat=1.0, polyols=3.0), row("10000001")], None, "2026-11-14")
    assert [c["code"] for c in doc["candidates"]] == ["10000001", "10000002"]
    assert set(doc["candidates"][1]["stored"]) == {"energy_kcal", "fat", "salt"}


def test_rows_are_left_out_and_counted():
    bad = [
        row("10000001", per=None),                 # legacy: no basis
        row("10000002", per=""),
        row("abc"),                                # bad barcode
        row("10000003", fat=float("nan")),         # not finite
        row("10000004", fat=-1.0),                 # negative
        row("10000005", sodium=lr.MAX_VALUE + 1),  # absurd
        row("10000006", fat="x"),                  # not a number
        {"code": "10000007", "nutrition_per": "100g"},   # no values at all
        row("10000008"), row("10000008"),          # duplicate
    ]
    doc, counts = ce.build_document(bad, None, "2026-11-14")
    assert [c["code"] for c in doc["candidates"]] == ["10000008"]
    assert counts["no_basis"] == 2 and counts["bad_code"] == 1 and counts["bad_value"] == 4 and counts["no_values"] == 1 and counts["duplicate"] == 1


def test_an_empty_export_is_refused():
    with pytest.raises(ce.ExportRefused):
        ce.build_document([], None, "2026-11-14")
    with pytest.raises(ce.ExportRefused):
        ce.build_document([row("10000001", per=None)], None, "2026-11-14")


def test_a_shrunk_export_is_refused_and_the_boundary_passes():
    prev, _ = ce.build_document(rows(100), None, "2026-11-13")
    ce.build_document(rows(70), prev, "2026-11-14")            # exactly 70%: allowed
    with pytest.raises(ce.ExportRefused):
        ce.build_document(rows(69), prev, "2026-11-14")


def test_a_broken_previous_file_does_not_block_the_export():
    doc, counts = ce.build_document(rows(3), {"candidates": "oops"}, "2026-11-14")
    assert len(doc["candidates"]) == 3 and counts["previous"] == 0
    doc, _ = ce.build_document(rows(3), {}, "2026-11-14")
    assert len(doc["candidates"]) == 3


def test_the_file_passes_the_stores_own_validation():
    doc, _ = ce.build_document(rows(20), None, "2026-11-14")
    assert all(st._clean_candidate(c) == c for c in doc["candidates"])


def test_sql_reads_the_newest_version_of_india_products_with_a_nutrition_error():
    sql = ce.candidate_sql()
    assert "silver_product_versions" in sql and "rn = 1" in sql and "order by last_modified_t desc" in sql
    assert "en:india" in sql and "data_quality_errors_tags" in sql and "'en:nutrition-%'" in sql
    for f in lr.FIELDS:
        assert f in sql


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "p8_steward" / "nightly_export"


def test_the_export_job_is_admin_owned_paused_first_and_points_at_a_real_notebook():
    bundle = yaml.safe_load((BUNDLE / "databricks.yml").read_text(encoding="utf-8"))
    job = yaml.safe_load((BUNDLE / "resources" / "export_job.yml").read_text(encoding="utf-8"))["resources"]["jobs"]["nightly_export"]
    assert bundle["variables"]["export_pause"]["default"] == "PAUSED"           # un-paused only after the dry run and one real run were checked
    assert bundle["variables"]["export_cron"]["default"] == "0 50 8 * * ?"       # after the 08:15 gold build and the 08:40 health job
    assert "run_as" not in job and job["max_concurrent_runs"] == 1
    assert len(job["tasks"]) == 1 and "retries" not in job["tasks"][0] and "max_retries" not in job["tasks"][0]
    notebook = (BUNDLE / "resources" / job["tasks"][0]["notebook_task"]["notebook_path"]).resolve()
    assert notebook == ROOT / "p8_steward" / "notebooks" / "export_nightly_candidates.py" and notebook.is_file()


def test_the_notebook_reads_only_the_names_the_setup_script_stores():
    text = (ROOT / "p8_steward" / "notebooks" / "export_nightly_candidates.py").read_text(encoding="utf-8")
    setup = (BUNDLE / "setup_export.py").read_text(encoding="utf-8")
    for name in ("hf_nightly_token", "healthchecks_nightly_export_ping_url"):
        assert name in text and name in setup
    assert 'SCOPE = "packsense_nightly"' in setup and '"packsense_nightly"' in text
