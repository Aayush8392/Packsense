import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import freeze_fix_test as ff  # noqa: E402


def test_models_seen_lists_every_model_name_and_flags_a_missing_one():
    readings = {"a": {"tokens": 5, "model": "gemini-3.5-flash-lite"}, "b": {"tokens": 7, "model": "gemini-3.5-flash-lite"}, "c": {"tokens": 3}, "d": {"tokens": 0, "skipped": "no table"}}
    assert ff.models_seen(readings) == ["None", "gemini-3.5-flash-lite"]


def test_the_frozen_files_exist_and_the_pass_condition_names_both_results_and_the_fixed_line_types():
    root = Path(__file__).resolve().parents[2]
    assert all((root / f).exists() for f in ff.FILES) and "photo_method.py" in " ".join(ff.FILES) and "run_round2_readers.py" in " ".join(ff.FILES)
    assert "80%" in ff.PASS["primary_result"] and "70%" in ff.PASS["check_result"] and ff.PASS["line_types"] == ["rule2", "rule1", "differ", "match"]
    assert "judge-2:" in ff.SAMPLING["random_70"] and "BEFORE any judging" in ff.SAMPLING["random_70"]


def test_an_existing_record_is_never_overwritten(tmp_path, monkeypatch):
    f = tmp_path / "freeze.json"
    f.write_text("{}")
    monkeypatch.setattr(ff, "OUT", f)
    monkeypatch.setattr(sys, "argv", ["freeze_fix_test.py", "write"])
    with pytest.raises(SystemExit, match="never overwritten"):
        ff.main()
    assert f.read_text() == "{}"
