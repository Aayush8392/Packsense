"""Gold never receives the hashed contributor columns.

The staging view reads them only to count distinct editors. Two checks, both generated from the contract so they cannot drift:
the view's EXCEPT list is exactly the contract's `egress: never` set, and `editors_hmac` is referenced exactly once outside that
list (the distinct_editors expression) while no other hashed column is referenced at all.
"""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "p2_lakehouse" / "contracts" / "silver.yml"
STAGING = ROOT / "p4_modelling" / "models" / "databricks" / "stg_silver_versions.sql"


def never_columns():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return {c["name"] for c in contract["columns"] if c.get("egress") == "never"}


def staging_sql():
    return STAGING.read_text(encoding="utf-8")


def except_list(sql):
    match = re.search(r"\*\s+except\s*\((.*?)\)", sql, re.S | re.I)
    assert match, "the staging view must use SELECT * EXCEPT (...)"
    return {name.strip() for name in match.group(1).split(",") if name.strip()}


def test_except_list_is_the_contracts_egress_never_set():
    assert except_list(staging_sql()) == never_columns()


def test_hashed_columns_are_only_used_to_count_editors():
    sql = staging_sql()
    outside = sql.replace(re.search(r"\*\s+except\s*\(.*?\)", sql, re.S | re.I).group(0), "")
    for name in never_columns():
        uses = len(re.findall(rf"\b{name}\b", outside))
        assert uses == (1 if name == "editors_hmac" else 0), f"{name} used {uses} times outside the EXCEPT list"


def test_contract_still_lists_the_hashed_columns():
    # guards the guard: if the contract's marker were renamed, the tests above would pass on an empty set
    assert len(never_columns()) >= 11
