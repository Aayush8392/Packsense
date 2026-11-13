"""Tests for the nightly freeze record (nightly/freeze_nightly.py): normalised hashes, every kind of difference, the fail-closed model check."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import freeze_fix_test as ff  # noqa: E402
from nightly import freeze_nightly as fz  # noqa: E402
from nightly.budget import Stop  # noqa: E402

FILES = ["a.py", "b.txt"]


def setup(tmp_path):
    (tmp_path / "a.py").write_bytes(b"x = 1\ny = 2\n")
    (tmp_path / "b.txt").write_bytes(b"hello\n")
    rec = tmp_path / "freeze.json"
    rec.write_text(json.dumps({"written_utc": "t", "record": fz.record(tmp_path, FILES)}), encoding="utf-8")
    return rec


def problems(tmp_path, rec):
    return fz.problems(rec, tmp_path, FILES)


def test_a_fresh_record_holds_and_crlf_line_endings_do_not_break_it(tmp_path):
    rec = setup(tmp_path)
    assert problems(tmp_path, rec) == []
    (tmp_path / "a.py").write_bytes(b"x = 1\r\ny = 2\r\n")           # the Windows checkout of the same file
    assert problems(tmp_path, rec) == []


def test_a_changed_file_is_named(tmp_path):
    rec = setup(tmp_path)
    (tmp_path / "b.txt").write_bytes(b"hello!\n")
    assert problems(tmp_path, rec) == ["b.txt"]


def test_a_missing_file_and_a_missing_record_are_problems(tmp_path):
    rec = setup(tmp_path)
    (tmp_path / "a.py").unlink()
    assert problems(tmp_path, rec) == ["a.py"]
    assert fz.problems(tmp_path / "nope.json", tmp_path, FILES) == ["no freeze record"]


def test_a_changed_model_or_prompt_is_named(tmp_path):
    rec = setup(tmp_path)
    doc = json.loads(rec.read_text(encoding="utf-8"))
    doc["record"]["model"] = "gemini-other"
    doc["record"]["prompts"]["photo"] = "0" * 64
    rec.write_text(json.dumps(doc), encoding="utf-8")
    assert problems(tmp_path, rec) == ["model", "prompts"]


def test_the_model_check_fails_closed():
    fz.check_model(fz.pm.MODEL)
    for bad in (None, "", "gemini-3.5-flash", fz.pm.MODEL + "-new"):
        with pytest.raises(Stop) as e:
            fz.check_model(bad)
        assert e.value.reason == "model_mismatch"


def test_the_file_list_exists_and_covers_the_round_2_method_files():
    missing = [f for f in fz.METHOD_FILES if not (fz.ROOT / f).exists()]
    assert missing == []
    assert set(ff.FILES) <= set(fz.METHOD_FILES)
