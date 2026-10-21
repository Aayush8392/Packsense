"""fetch_site_data.py against a fake Hugging Face (an opener that serves bytes): hash check, path check, token handling."""
import hashlib
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_site_data as fs  # noqa: E402


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake(files: dict, seen: list):
    def opener(req, timeout=0):
        seen.append(req)
        name = req.full_url.split("/resolve/main/site%2F")[-1] if "site%2F" in req.full_url else req.full_url.split("/resolve/main/site/")[-1]
        if name not in files:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return Resp(files[name])
    return opener


def release(**over):
    data = b"a,b\n1,2\n"
    manifest = {"built_at_utc": "x", "files": [{"path": "d.csv", "kind": "data", "sha256": hashlib.sha256(data).hexdigest()}]}
    manifest.update(over)
    return {"release_manifest.json": json.dumps(manifest).encode(), "d.csv": data}


def test_a_good_release_is_fetched_and_written(tmp_path):
    seen = []
    m = fs.fetch("o/r", tmp_path, "tok", fake(release(), seen))
    assert (tmp_path / "d.csv").read_bytes() == b"a,b\n1,2\n" and m["built_at_utc"] == "x"
    assert all(r.headers["Authorization"] == "Bearer tok" for r in seen)


def test_a_changed_file_is_refused(tmp_path):
    files = release()
    files["d.csv"] = b"a,b\n1,3\n"
    with pytest.raises(fs.FetchError, match="sha256"):
        fs.fetch("o/r", tmp_path, "tok", fake(files, []))


def test_a_missing_file_is_refused(tmp_path):
    files = release()
    del files["d.csv"]
    with pytest.raises(fs.FetchError, match="404"):
        fs.fetch("o/r", tmp_path, "tok", fake(files, []))


@pytest.mark.parametrize("bad", ["../x.csv", "sub/x.csv", "", "..\\x.csv"])
def test_a_path_outside_the_folder_is_refused(tmp_path, bad):
    files = release(files=[{"path": bad, "kind": "data"}])
    with pytest.raises(fs.FetchError, match="refusing path"):
        fs.fetch("o/r", tmp_path / "out", "tok", fake(files, []))


def test_the_token_is_never_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HF_SITE_READ_TOKEN", "hf_secret_value")
    monkeypatch.setattr(fs, "fetch", lambda *a, **k: (_ for _ in ()).throw(fs.FetchError("x: HTTP 401")))
    assert fs.main(["o/r", str(tmp_path)]) == 1
    assert "hf_secret_value" not in capsys.readouterr().out


def test_a_missing_token_stops_before_any_request(tmp_path, monkeypatch):
    monkeypatch.delenv("HF_SITE_READ_TOKEN", raising=False)
    assert fs.main(["o/r", str(tmp_path)]) == 2
