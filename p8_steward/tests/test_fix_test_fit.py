import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fix_test_fit as f  # noqa: E402


def test_fit_counts_violations_and_checked_rules():
    bad = f.fit({"sugars": 30.0, "carbohydrates": 20.0})
    assert "sugars-plus-starch-greater-than-carbohydrates" in bad["violated"]
    good = f.fit({"sugars": 3.0, "carbohydrates": 20.0})
    assert good["violated"] == [] and good["checked"] >= 1


def test_pair_classes():
    clean, dirty = {"violated": []}, {"violated": ["x"]}
    assert f.pair(clean, clean) == "both_clean" and f.pair(dirty, clean) == "key_clean_only"
    assert f.pair(clean, dirty) == "code_clean_only" and f.pair(dirty, dirty) == "both_violate"
