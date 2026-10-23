"""fetch_site_data.py with the product-card files: one sub-folder (cards/) is allowed, fetched in parallel, and every file is verified against the manifest."""
import hashlib
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import fetch_site_data as fs  # noqa: E402
from test_fetch_site_data import fake, release  # noqa: E402


def with_cards(n):
    files = release()
    manifest = json.loads(files["release_manifest.json"])
    for i in range(n):
        data = f"code\n{i}\n".encode()
        files[f"cards/{i:03d}.csv"] = data
        manifest["files"].append({"path": f"cards/{i:03d}.csv", "kind": "card", "sha256": hashlib.sha256(data).hexdigest()})
    files["release_manifest.json"] = json.dumps(manifest).encode()
    return files


def test_files_in_one_sub_folder_are_fetched_in_parallel_and_verified(tmp_path):
    fs.fetch("o/r", tmp_path, "tok", fake(with_cards(40), []))
    assert (tmp_path / "cards" / "039.csv").read_bytes() == b"code\n39\n"
    assert len(list((tmp_path / "cards").glob("*.csv"))) == 40


def test_a_changed_card_file_is_refused(tmp_path):
    files = with_cards(5)
    files["cards/003.csv"] = b"code\nX\n"
    with pytest.raises(fs.FetchError, match="sha256"):
        fs.fetch("o/r", tmp_path, "tok", fake(files, []))


def test_a_missing_card_file_is_refused(tmp_path):
    files = with_cards(5)
    del files["cards/002.csv"]
    with pytest.raises(fs.FetchError, match="404"):
        fs.fetch("o/r", tmp_path, "tok", fake(files, []))
