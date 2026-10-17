"""The flag-occurrence view reads exactly the four OFF flag columns that silver keeps (generated from the contract)."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "p2_lakehouse" / "contracts" / "silver.yml"
SQL = ROOT / "p4_modelling" / "models" / "databricks" / "stg_flag_occurrences.sql"


def contract_flag_columns():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    return {c["name"]: c for c in contract["columns"] if re.fullmatch(r"data_quality_\w+_tags", c["name"])}


def test_view_reads_every_flag_column_of_the_contract_and_nothing_else():
    wanted = set(contract_flag_columns())
    used = set(re.findall(r"'(data_quality_\w+_tags)'", SQL.read_text(encoding="utf-8")))
    assert wanted == used, (wanted, used)


def test_flag_columns_are_string_arrays():
    columns = contract_flag_columns()
    assert len(columns) == 4
    assert all(c["type"] == "array<string>" for c in columns.values())


def test_each_severity_label_is_unique():
    labels = re.findall(r"\('(\w+)', 'data_quality_\w+_tags'\)", SQL.read_text(encoding="utf-8"))
    assert sorted(labels) == ["bug", "error", "info", "warning"]
