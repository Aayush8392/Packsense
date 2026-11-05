"""The unreadable-card check must never touch the test part and must pick exactly the cards the owner could not use."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p8_steward" / "bootstrap"))
sys.path.insert(0, str(ROOT / "p8_steward"))
import dev_unreadable_check as duc  # noqa: E402


def test_only_development_parts_are_ever_read():
    assert set(duc.PARTS) == {"dev", "dev2"}
    assert "test" not in duc.OUT.name


def test_unreadable_cards_are_the_unusable_entries():
    key = {"1": {"usable": True}, "2": {"usable": False, "reason": "the owner could not read the table"}, "3": {"usable": False}}
    assert set(duc.unreadable_cards(key)) == {"2", "3"}
