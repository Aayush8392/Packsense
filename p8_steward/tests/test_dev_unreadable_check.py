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


def test_photo_ref_embeds_by_default_and_gives_a_plain_address_with_a_base(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "p8_steward" / "labelling"))
    import build_answer_key_tasks as bt
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "123.jpg").write_bytes(b"abc")
    monkeypatch.setattr(bt, "SET", tmp_path)
    assert bt.photo_ref("123.jpg", None) == "data:image/jpeg;base64,YWJj"
    assert bt.photo_ref("123.jpg", "http://127.0.0.1:8090/") == "http://127.0.0.1:8090/123.jpg"
