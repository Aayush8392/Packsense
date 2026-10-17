"""Every comparison of written names goes through the name_key macro, so the engines cannot disagree about case folding again."""
import re
from pathlib import Path

P4 = Path(__file__).resolve().parents[1]


def sql_files():
    return list((P4 / "models" / "portable").glob("*.sql")) + list((P4 / "data_tests").glob("*.sql"))


def test_no_portable_model_or_test_lower_cases_a_name_by_hand():
    offenders = [f.name for f in sql_files() if re.search(r"lower\s*\(\s*trim\s*\(", f.read_text(encoding="utf-8"))]
    assert not offenders, f"use the name_key macro instead of lower(trim(...)) in: {offenders}"


def test_the_macro_removes_the_combining_dot_and_folds_the_final_sigma():
    macro = (P4 / "macros" / "engine.sql").read_text(encoding="utf-8")
    body = macro[macro.index("macro name_key"):]
    assert "̇" in body or "\u0307" in body
    assert "ς" in body and "σ" in body
