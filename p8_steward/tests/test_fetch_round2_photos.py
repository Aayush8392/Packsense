import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import fetch_round2_photos as f  # noqa: E402


def test_the_display_address_is_rewritten_to_the_full_photo_and_a_missing_one_is_empty():
    assert f.full_address({"en": "https://images.openfoodfacts.org/images/products/123/nutrition_en.4.400.jpg"}) == "https://images.openfoodfacts.org/images/products/123/nutrition_en.4.full.jpg"
    assert f.full_address({}) == "" and f.full_address({"en": ""}) == ""


def test_the_long_side_becomes_1600_and_a_small_photo_is_never_enlarged():
    assert f.target_size(3200, 2400) == (1600, 1200) and f.target_size(1200, 4800) == (400, 1600)
    assert f.target_size(800, 600) == (800, 600) and f.target_size(1600, 1600) == (1600, 1600)
