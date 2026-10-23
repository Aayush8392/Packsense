"""The SQL model product_rule_verdicts against its Python twin p7_triage_ml/rules_lib.py, row for row.

The model's COMPILED SQL (target/compiled, written by `dbt build --target duckdb`) is run on a temporary copy of the REAL fixture sets that OFF checks, plus
variants of each real set made by changing one field at a time (a missing value, zero, halved, doubled, nudged past a tolerance, an impossible 150) and a grid of
energy pairs around every energy limit. Every row's status and severity must equal the Python verdict, and the deviation must agree within rounding.

The test needs the DuckDB fixture build; without it the test is skipped (the CI job `engines` builds it first, then runs this file).
The tolerances written in the model (the `set` lines at its top) must also equal the constants of rules_lib.
"""
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
P4 = HERE.parent
ROOT = P4.parent
sys.path.insert(0, str(ROOT / "p7_triage_ml"))
import rules_lib as rl  # noqa: E402

MODEL = P4 / "models" / "portable" / "product_rule_verdicts.sql"
COMPILED = P4 / "target" / "compiled" / "packsense" / "models" / "portable" / "product_rule_verdicts.sql"
DB = P4 / "target" / "fixture.duckdb"

# model constant -> rules_lib constant
CONSTANTS = {
    "KJ_PER_KCAL_LOW": "KJ_PER_KCAL_LOW", "KJ_PER_KCAL_HIGH": "KJ_PER_KCAL_HIGH", "KJ_KCAL_SLACK": "KJ_KCAL_SLACK",
    "ENERGY_ERROR_RATIO": "ENERGY_ERROR_RATIO", "ENERGY_WARNING_RATIO": "ENERGY_WARNING_RATIO", "ENERGY_SLACK": "ENERGY_SLACK",
    "ENERGY_MIN_KJ": "ENERGY_MIN_KJ", "ENERGY_MIN_KCAL": "ENERGY_MIN_KCAL", "SALT_PER_SODIUM": "SALT_PER_SODIUM",
    "SALT_SODIUM_TOLERANCE": "SALT_SODIUM_TOLERANCE", "PART_TOLERANCE_SMALL": "PART_TOLERANCE_SMALL",
    "PART_TOLERANCE_LARGE": "PART_TOLERANCE_LARGE", "PART_LARGE_FROM": "PART_LARGE_FROM", "NUTRIENT_MAX_G": "NUTRIENT_MAX_G",
    "TOTAL_MAX_G": "TOTAL_MAX_G", "ENERGY_MAX_KJ": "ENERGY_MAX_KJ",
}
# nutrient column -> the key rules_lib reads
KEYS = {"energy_kj": "energy-kj", "energy_kcal": "energy-kcal", "fat": "fat", "saturated_fat": "saturated-fat", "carbohydrates": "carbohydrates",
        "sugars": "sugars", "starch": "starch", "fiber": "fiber", "proteins": "proteins", "salt": "salt", "sodium": "sodium", "polyols": "polyols",
        "erythritol": "erythritol", "isomalt": "isomalt", "maltitol": "maltitol", "sorbitol": "sorbitol", "alcohol": "alcohol"}
MASS = [c for c in KEYS if not c.startswith("energy") and c != "alcohol"]     # the columns the 'value over 105' maximum is taken over (alcohol is % vol)
NUTRIENT_COLUMNS = list(KEYS)
TEXT_COLUMNS = ("code", "source", "preparation", "per", "per_unit")


def test_the_tolerances_in_the_model_equal_rules_lib():
    text = MODEL.read_text(encoding="utf-8")
    found = {m.group(1): float(m.group(2)) for m in re.finditer(r"\{% set (\w+) = ([0-9.]+) %\}", text)}
    for name, lib_name in CONSTANTS.items():
        assert name in found, f"{name} is not set in the model"
        assert found[name] == float(getattr(rl, lib_name)), name
    assert found["TRACE_CARBOHYDRATES"] == rl.TRACE_G["carbohydrates"] and found["TRACE_FAT"] == rl.TRACE_G["fat"]
    assert {k for k in found} == set(CONSTANTS) | {"TRACE_CARBOHYDRATES", "TRACE_FAT"}


def _variants(row: dict):
    """The real set itself, then one-field changes of it."""
    yield dict(row)
    for col in NUTRIENT_COLUMNS:
        v = row[col]
        changes = [None, 0.0, 150.0]
        if v is not None:
            changes += [v * 0.5, v * 2, v + 0.05, v + 0.11, v - 0.05, v + 3.0]
        for c in changes:
            r = dict(row)
            r[col] = c
            yield r


def _energy_grid(base: dict):
    for kj in (None, 0.0, 50.0, 55.0, 56.0, 100.0, 1000.0, 3911.0, 3912.0, 4000.0):
        for kcal in (None, 0.0, 13.0, 14.0, 25.0, 250.0, 300.0, 940.0, 3911.0, 4000.0):
            r = dict(base)
            r["energy_kj"], r["energy_kcal"] = kj, kcal
            yield r


def _literal(v) -> str:
    """A SQL literal for a test value: NULL, a boolean, a number (repr round-trips a float exactly) or a quoted string."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(float(v))
    return "'" + str(v).replace("'", "''") + "'"


def _prepare(r: dict) -> dict:
    r = dict(r)
    masses = [r[c] for c in MASS if r[c] is not None]
    r["max_mass_g"] = max(masses) if masses else None
    return r


def _expected(r: dict):
    n = {KEYS[c]: r[c] for c in NUTRIENT_COLUMNS if r[c] is not None}
    out = rl.verdicts(n)
    # alcohol is % vol, not a mass: the SQL leaves it out of the 'value over 105' maximum (it can never exceed 100 anyway), so the twin is asked the same question
    out["value-over-105"] = rl.value_over_105({k: v for k, v in n.items() if k != "alcohol"})
    return out


@pytest.mark.skipif(not (DB.exists() and COMPILED.exists()), reason="needs the DuckDB fixture build (dbt build --target duckdb)")
def test_sql_and_python_verdicts_agree_on_real_sets_and_their_variants():
    import duckdb

    src = duckdb.connect(str(DB), read_only=True)
    cols = [d[0] for d in src.execute("select * from product_nutrition_sets limit 0").description]
    real = [dict(zip(cols, t)) for t in src.execute(
        "select * from product_nutrition_sets where not is_estimate and per in ('100g', '100ml') order by code, source, preparation, per, per_quantity").fetchall()]
    src.close()
    assert len(real) > 100

    cases = []
    for base in real:
        cases.extend(_variants(base))
    cases.extend(_energy_grid(real[0]))
    cases.extend(_energy_grid({**real[1], "carbohydrates": 10.0, "fat": 5.0, "proteins": 3.0, "fiber": 1.0}))
    cases = [_prepare(c) for c in cases]
    for i, c in enumerate(cases):
        c["code"], c["source"], c["preparation"], c["per"], c["per_quantity"] = f"case{i}", "packaging", "as_sold", "100g", 100.0
        c["is_estimate"] = False

    con = duckdb.connect(":memory:")
    names = list(real[0])
    con.execute("create table sets (" + ", ".join(f'"{n}" {"BOOLEAN" if n == "is_estimate" else "VARCHAR" if n in TEXT_COLUMNS else "DOUBLE"}' for n in names) + ")")
    for start in range(0, len(cases), 500):                       # multi-row VALUES: executemany is row by row and far too slow for ~30,000 cases
        rows = [", ".join(_literal(c.get(n)) for n in names) for c in cases[start:start + 500]]
        con.execute("insert into sets values " + ", ".join(f"({r})" for r in rows))
    sql = re.sub(r'"[^"]+"\."[^"]+"\."product_nutrition_sets"', "sets", COMPILED.read_text(encoding="utf-8"))
    assert "sets" in sql and "product_nutrition_sets" not in sql
    got = {}
    for code, rule, status, severity, deviation in con.execute(f"select code, rule, status, severity, deviation from ({sql})").fetchall():
        got[(code, rule)] = (status, severity, deviation)
    assert len(got) == len(cases) * len(rl.RULES)

    bad = []
    seen_violation = set()
    for c in cases:
        for rule, want in _expected(c).items():
            status, severity, deviation = got[(c["code"], rule)]
            if want.status == "violated":
                seen_violation.add(rule)
            same = status == want.status and severity == want.severity and (
                (deviation is None) == (want.deviation is None) and (deviation is None or abs(deviation - want.deviation) <= 2e-4))
            if not same:
                bad.append((c["code"], rule, (status, severity, deviation), (want.status, want.severity, want.deviation)))
    assert not bad, f"{len(bad)} disagreements of {len(got)}; first: {bad[:5]}"
    assert seen_violation == set(rl.RULES), f"rules never violated by any case: {set(rl.RULES) - seen_violation}"
