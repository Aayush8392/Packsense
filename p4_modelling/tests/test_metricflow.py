"""The MetricFlow metrics (models/portable/semantic.yml) against direct SQL on the REAL fixture build, number for number.

Every metric is queried through `mf query` on the DuckDB fixture (target/fixture.duckdb, written by `dbt build --target duckdb`) and compared with a plain SQL
aggregation of the same gold table. The test needs MetricFlow (requirements-duckdb.txt) and the fixture build; without them it is skipped (the CI job
`engines` builds the fixture first). MetricFlow runs only on DuckDB: it is not run on Databricks, see the README.
"""
import csv
import os
import shutil
import subprocess
from pathlib import Path

import duckdb
import pytest

P4 = Path(__file__).resolve().parents[1]
DB = P4 / "target" / "fixture.duckdb"
MF = shutil.which("mf")

REQUIRED = os.environ.get("PACKSENSE_REQUIRE_METRICFLOW") == "1"   # set by the CI job `engines`: there a missing MetricFlow or fixture fails instead of skipping
pytestmark = pytest.mark.skipif((MF is None or not DB.exists()) and not REQUIRED, reason="MetricFlow or the DuckDB fixture build is not available")

COVERAGE = {
    "nutrition_coverage": "n_with_nutrition", "nutriscore_coverage": "n_with_nutriscore", "nova_coverage": "n_with_nova",
    "quantity_coverage": "n_with_quantity", "ingredients_coverage": "n_with_ingredients", "categories_coverage": "n_with_categories",
    "labels_coverage": "n_with_labels",
}


def query(metrics: list[str], group_by: str, tmp_path: Path) -> list[dict]:
    out = tmp_path / "result.csv"
    env = {**os.environ, "DBT_PROFILES_DIR": str(P4 / "mf_profiles"), "PYTHONUTF8": "1"}
    done = subprocess.run([MF, "query", "--metrics", ",".join(metrics), "--group-by", group_by, "--order", group_by, "--csv", str(out)],
                          cwd=P4, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    return list(csv.DictReader(out.open(encoding="utf-8")))


def sql(statement: str) -> list[tuple]:
    """Direct SQL on the fixture. The connection is closed at once: MetricFlow opens the same file and DuckDB allows one process at a time."""
    c = duckdb.connect(str(DB), read_only=True)
    try:
        return c.execute(statement).fetchall()
    finally:
        c.close()


def test_products_held_and_completeness_by_scope(tmp_path):
    got = {r["scorecard__scope"]: r for r in query(["products_held", "coverage_points", "completeness"], "scorecard__scope", tmp_path)}
    want = sql("select scope, sum(n_products), sum(coverage_points) from mart_brand_scorecard group by scope")
    assert {w[0] for w in want} == set(got) and len(want) == 2
    for scope, products, points in want:
        assert float(got[scope]["products_held"]) == products
        assert float(got[scope]["coverage_points"]) == points
        assert float(got[scope]["completeness"]) == pytest.approx(points / (7.0 * products))


def test_every_field_coverage_ratio_by_scope(tmp_path):
    got = {r["scorecard__scope"]: r for r in query(list(COVERAGE), "scorecard__scope", tmp_path)}
    for metric, column in COVERAGE.items():
        for scope, products, filled in sql(f"select scope, sum(n_products), sum({column}) from mart_brand_scorecard group by scope"):
            assert float(got[scope][metric]) == pytest.approx(filled / products), (metric, scope)


def test_open_flag_spans_per_day(tmp_path):
    got = {r["metric_time__day"][:10]: r for r in query(["open_flag_spans", "open_error_spans"], "metric_time__day", tmp_path)}
    want = sql("select snapshot_date, sum(open_spans), sum(case when severity = 'error' then open_spans else 0 end) "
               "from fct_catalogue_quality_daily group by snapshot_date order by snapshot_date")
    assert len(want) > 10
    for day, spans, errors in want:
        assert float(got[str(day)]["open_flag_spans"]) == spans, day
        assert float(got[str(day)]["open_error_spans"]) == errors, day
