"""The steward's review set (item 22/23): the flag grouping, the choice of products, the SQL and Python agreeing, and the exit code staying identical to the fixture's."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward"))
import review_set_lib as rsl  # noqa: E402

FIXTURE = ROOT / "p4_modelling" / "fixtures" / "stg_silver_versions.jsonl"


def real_flags() -> list[str]:
    flags = set()
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            flags.update(json.loads(line).get("data_quality_errors_tags") or [])
    return sorted(flags)


def test_known_flags_fall_in_the_expected_groups():
    p = "en:nutrition-packaging-as-sold-100g-"
    assert rsl.group_of(p + "energy-value-in-kcal-does-not-match-value-in-kj") == "A_energy_mismatch"
    assert rsl.group_of(p + "energy-value-in-kj-does-not-match-value-computed-from-other-nutrients") == "A_energy_mismatch"
    assert rsl.group_of(p + "salt-does-not-match-sodium") == "B_salt_vs_sodium"
    assert rsl.group_of("en:nutrition-value-over-105-fat") == "C_values_too_large"
    assert rsl.group_of("en:nutrition-value-over-3800-energy") == "C_values_too_large"
    assert rsl.group_of(p + "sugars-plus-starch-greater-than-carbohydrates") == "D_sums_too_large"
    assert rsl.group_of("en:nutrition-saturated-fat-greater-than-fat") == "D_sums_too_large"
    assert rsl.group_of("en:nutrition-data-per-serving-missing-serving-size") == "E_other_nutrition"
    assert rsl.group_of("en:mutually-exclusive-tags-for-categories-dairies-and-categories-vegan-products") is None


def test_the_sql_grouping_agrees_with_the_python_grouping_on_every_real_flag_of_the_fixture():
    flags = [f for f in real_flags() if f.startswith(rsl.PREFIX)]
    assert len(flags) >= 8
    con = duckdb.connect()
    con.execute("create table f (flag varchar)")
    con.executemany("insert into f values (?)", [(f,) for f in flags])
    rows = con.execute(f"select flag, {rsl.group_case_sql('flag')} from f").fetchall()
    for flag, rank in rows:
        assert rsl.group_name(rank) == rsl.group_of(flag), flag


def candidates(n_india=40, n_other=40, group="A_energy_mismatch", start=0):
    return [{"code": f"{group[0]}{i:05d}", "group": group, "india": 1 if i < n_india else 0, "h": f"{(i * 7919 + start) % 100003:06d}"} for i in range(n_india + n_other)]


def test_choose_is_deterministic_respects_the_india_share_and_the_limit():
    pool = candidates()
    a, report = rsl.choose(pool, 36, 22)
    b, _ = rsl.choose(list(reversed(pool)), 36, 22)
    assert [c["code"] for c in a] == [c["code"] for c in b]
    assert len(a) == 36 and sum(c["india"] for c in a) == 22
    assert report["per_group"]["A_energy_mismatch"] == {"taken": 36, "india": 22, "available": 80}
    assert "A_energy_mismatch" not in report["short_groups"] and "B_salt_vs_sodium" in report["short_groups"]    # B has no candidates at all


def test_choose_leaves_out_excluded_codes_and_lets_one_side_fill_when_the_other_is_short():
    pool = candidates(n_india=10, n_other=50)
    chosen, _ = rsl.choose(pool, 36, 22, exclude={pool[0]["code"]})
    assert pool[0]["code"] not in {c["code"] for c in chosen}
    assert len(chosen) == 36 and sum(c["india"] for c in chosen) == 9           # only 9 India products are left, the rest are non-India
    few_other = candidates(n_india=40, n_other=3)
    chosen, _ = rsl.choose(few_other, 36, 22)
    assert len(chosen) == 36 and sum(c["india"] for c in chosen) == 33


def test_no_product_is_chosen_twice():
    pool = candidates() + candidates(group="B_salt_vs_sodium")
    chosen, _ = rsl.choose(pool, 36, 22)
    assert len({c["code"] for c in chosen}) == len(chosen)


def exit_section(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    start = text.index("# COMMAND ----------\n# 2. Every version")
    return text[start:]


def test_the_exit_function_code_is_identical_to_the_fixture_notebook():
    """Sections 2 to the end (the exit function and the writing) are one copy of the fixture notebook's: a change to one must be made in the other."""
    ours = exit_section(ROOT / "p8_steward" / "notebooks" / "export_review_set.py")
    theirs = exit_section(ROOT / "p4_modelling" / "notebooks" / "export_fixture.py")
    assert ours == theirs


def test_the_review_set_never_goes_through_the_fixture_fetcher_paths():
    fetch = (ROOT / "p8_steward" / "bootstrap" / "fetch_review_set.py").read_text(encoding="utf-8")
    local_dir_line = [line for line in fetch.splitlines() if line.startswith("LOCAL_DIR =")][0]
    assert '"output" / "review_set"' in local_dir_line and "p4_modelling" not in local_dir_line and "fixtures" not in local_dir_line
