import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ocr_variant_test as o  # noqa: E402

TRUTH = {"fat": 3.0, "carbohydrates": 20.0, "proteins": 5.0, "sodium": 0.2}


def test_agree_needs_three_shared_fields_and_ninety_percent_within_tolerance():
    assert o.agree({"fat": 3.1, "carbohydrates": 20.5, "proteins": 5.0, "sodium": 0.2}, TRUTH)
    assert not o.agree({"fat": 30.0, "carbohydrates": 20.0, "proteins": 5.0, "sodium": 0.2}, TRUTH, thr=0.9)       # one of four wrong = 75%
    assert not o.agree({"fat": 3.0, "carbohydrates": 20.0}, TRUTH)                                                  # only two shared fields


def test_verdict_and_truth_table():
    key = {"A": "hybrid", "B": "contributor"}
    assert o.verdict("A", key) == "hybrid" and o.verdict("B", key) == "contributor" and o.verdict("both", key) == "both" and o.verdict("unsure", key) == "unsure"
    h, c = {"fat": 1.0}, {"fat": 2.0}
    assert o.truth_table("hybrid", h, c) is h and o.truth_table("contributor", h, c) is c and o.truth_table("both", h, c) is c and o.truth_table("neither", h, c) is None


def test_reading_of_drops_values_not_printed_in_the_text_and_converts_per_serving():
    text = "Fat 6 g  Carbohydrate 10 g  Protein 2 g  Serving size 30 g"
    entry = {"reading": {"basis": "per serving only", "serving_size": "30 g", "values_per_100": {"fat": 6, "carbohydrates": 10, "proteins": 2, "sodium": 77}}}
    got = o.reading_of(entry, text)
    assert got is not None and abs(got["fat"] - 20.0) < 1e-6 and "sodium" not in got                                # 77 is not printed: dropped; 6 g per 30 g serving = 20 per 100
    assert o.reading_of({"reading": None}, text) is None
