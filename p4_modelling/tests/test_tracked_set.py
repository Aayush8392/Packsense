"""The tracked set (the columns whose change opens a new history period) is checked against the silver contract.

The lists live in macros/tracked.sql; these tests read them from that file so the macro and the checks cannot drift apart.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "p2_lakehouse" / "contracts" / "silver.yml"
MACRO = ROOT / "p4_modelling" / "macros" / "tracked.sql"

# decided 2026-10-17: volatile or derived, kept per version in staging but never opening a period
NOT_TRACKED = {
    "completeness", "popularity_key", "unique_scans_n", "states_tags", "rev", "last_checked_t", "serving_quantity",
    "nutrient_levels_tags", "input_sets", "data_quality_errors_tags", "data_quality_warnings_tags", "data_quality_info_tags",
    "data_quality_bugs_tags", "created_t", "last_modified_t", "schema_version", "lc", "product_type",
}


def contract_columns():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return {c["name"]: c for c in contract["columns"]}


def macro_list(name):
    text = MACRO.read_text(encoding="utf-8")
    body = re.search(rf"macro {name}\(\) %\}}\s*\{{\{{ return\(\[(.*?)\]\) \}}\}}", text, re.S)
    assert body, f"macro {name} not found"
    return re.findall(r"'([a-z0-9_]+)'", body.group(1))


def tracked():
    return macro_list("tracked_scalars") + macro_list("tracked_arrays") + ["nutrients"]


def test_every_tracked_column_exists_in_the_contract():
    columns = contract_columns()
    missing = [c for c in tracked() if c not in columns]
    assert not missing, f"tracked but not in silver: {missing}"


def test_no_tracked_column_is_hashed_or_egress_never():
    columns = contract_columns()
    bad = [c for c in tracked() if columns[c].get("egress") == "never" or columns[c].get("class") == "hashed"]
    assert not bad, f"hashed columns in the tracked set: {bad}"


def test_volatile_and_derived_columns_are_not_tracked():
    assert not (set(tracked()) & NOT_TRACKED)


def test_no_duplicates_and_tag_columns_are_arrays():
    names = tracked()
    assert len(names) == len(set(names))
    columns = contract_columns()
    for c in macro_list("tracked_arrays"):
        assert columns[c]["type"] == "array<string>", c
    for c in macro_list("tracked_scalars"):
        assert not columns[c]["type"].startswith(("array", "map")), c


def test_the_tracked_set_is_the_agreed_size():
    # 32 scalar columns, 10 tag arrays and the nutrients map; a change here is a design change: update the decision first
    assert (len(macro_list("tracked_scalars")), len(macro_list("tracked_arrays"))) == (32, 10)
