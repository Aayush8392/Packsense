"""bootstrap/upload_bot_bundle.py: the folder check that runs before anything is uploaded (the upload itself is not run in tests)."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_site_data as fs  # noqa: E402
import upload_bot_bundle as ub  # noqa: E402


def make(folder: Path):
    files = {}
    for name in fs.BOT_REQUIRED:
        data = name.encode()
        (folder / f"{name}.000").write_bytes(data)
        files[name] = {"bytes": len(data), "chunks": [{"path": f"{name}.000", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}]}
    (folder / "bot_files.json").write_text(json.dumps({"version": "v", "files": files}), encoding="utf-8")


def test_a_good_folder_lists_manifest_and_chunks(tmp_path):
    make(tmp_path)
    names = ub.check_folder(tmp_path)
    assert names[0] == "bot_files.json" and len(names) == 1 + len(fs.BOT_REQUIRED)


def test_a_missing_chunk_a_changed_chunk_and_a_stray_file_are_refused(tmp_path):
    make(tmp_path)
    (tmp_path / "vocab.txt.000").write_bytes(b"x")
    with pytest.raises(fs.FetchError, match="does not match"):
        ub.check_folder(tmp_path)
    (tmp_path / "vocab.txt.000").unlink()
    with pytest.raises(fs.FetchError, match="missing from the folder"):
        ub.check_folder(tmp_path)
    make(tmp_path)
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(fs.FetchError, match="does not list"):
        ub.check_folder(tmp_path)


def test_a_dry_run_and_a_missing_token_upload_nothing(tmp_path, monkeypatch, capsys):
    make(tmp_path)
    assert ub.main([str(tmp_path), "--dry-run"]) == 0
    monkeypatch.delenv("HF_SITE_WRITE_TOKEN", raising=False)
    assert ub.main([str(tmp_path)]) == 2
    assert "hf_" not in capsys.readouterr().out
