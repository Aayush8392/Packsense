"""The Spark-to-DuckDB type mapping behind the fixture loader, checked against every type the real manifest uses."""
import json
import sys
from pathlib import Path

import pytest

P4 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(P4))

from gold_lib import fixture_load  # noqa: E402


@pytest.mark.parametrize("spark, duck", [
    ("string", "VARCHAR"), ("double", "DOUBLE"), ("bigint", "BIGINT"), ("int", "INTEGER"), ("boolean", "BOOLEAN"),
    ("timestamp", "TIMESTAMP"), ("array<string>", "VARCHAR[]"),
    ("map<string,struct<value:double,unit:string,modifier:string>>", 'MAP(VARCHAR, STRUCT("value" DOUBLE, "unit" VARCHAR, "modifier" VARCHAR))'),
])
def test_known_types(spark, duck):
    assert fixture_load.duckdb_type(spark) == duck


def test_nested_array_of_struct_with_a_map():
    t = "array<struct<source:string,per_quantity:double,nutrients:map<string,struct<value:double,unit:string>>>>"
    assert fixture_load.duckdb_type(t) == (
        'STRUCT("source" VARCHAR, "per_quantity" DOUBLE, "nutrients" MAP(VARCHAR, STRUCT("value" DOUBLE, "unit" VARCHAR)))[]')


def test_an_unknown_type_is_refused_not_guessed():
    with pytest.raises(ValueError):
        fixture_load.duckdb_type("decimal(10,2)")


def test_every_column_of_the_committed_manifest_maps():
    manifest = json.loads((P4 / "fixtures" / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["columns"]) > 50
    for name, spark_type in manifest["columns"].items():
        assert fixture_load.duckdb_type(spark_type), name
