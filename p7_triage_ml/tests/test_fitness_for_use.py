"""The fitness-for-use report: the SQL names the five core nutrients, defaults to India and warns about the all-market stability artefact. The figures themselves are checked when the
report runs against gold (the category rows must add up to the products held: the script asserts it)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "analysis"))
import fitness_for_use as ff  # noqa: E402


def test_the_report_asks_for_the_five_core_nutrients_the_newest_period_and_the_edits_of_the_last_days():
    sql = ff.report_sql("packsense_gold", "en:india", 28)
    for n in ("energy_kcal", "fat", "carbohydrates", "proteins", "salt"):
        assert f"h.{n} is not null" in sql
    assert "h.is_latest_observed = 1" in sql and "p.opened_by_seed = false" in sql and "date_sub(current_date(), 28)" in sql and "m.market_code = 'en:india'" in sql
    assert "bridge_product_market" not in ff.report_sql("packsense_gold", None, 28)


def test_the_default_is_india_and_the_all_market_run_warns():
    text = (HERE.parents[0] / "analysis" / "fitness_for_use.py").read_text(encoding="utf-8")
    assert 'default="en:india"' in text and "--all-markets" in text and "the 'changed' column is an artefact" in text
