"""fetch_site_data.py against a fake Hugging Face (an opener that serves bytes): hash check, path check, token handling."""
import hashlib
import io
import json
import sys
import urllib.error
import urllib.parse
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
        name = urllib.parse.unquote(name)
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


@pytest.mark.parametrize("bad", ["../x.csv", "a/b/x.csv", "cards/../x.csv", "/x.csv", "", "..\\x.csv", "cards/.."])
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


# ---- the question-bot bundle (bot/ in the same private dataset) ----

def bot_bundle(drop=None, **over):
    """A good bundle: every required file in two chunks, with the manifest the bundle maker writes."""
    files, served = {}, {}
    for name in fs.BOT_REQUIRED:
        parts = [name.encode() + b"-part-0", name.encode() + b"-part-1"]
        chunks = []
        for i, data in enumerate(parts):
            path = f"{name}.{i:03d}"
            served[path] = data
            chunks.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        files[name] = {"bytes": sum(len(p) for p in parts), "chunks": chunks}
    if drop:
        del files[drop]
    served["bot_files.json"] = json.dumps({"version": "v1", "files": files, **over}).encode()
    return served


def fake_bot(served: dict):
    def opener(req, timeout=0):
        name = urllib.parse.unquote(req.full_url.split("/resolve/main/bot/")[-1])
        if "/resolve/main/bot/" not in req.full_url or name not in served:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return Resp(served[name])
    return opener


def test_the_required_bot_files_equal_the_bundle_makers_list():
    text = (Path(__file__).resolve().parents[1] / "bot" / "port" / "make_bot_bundle.mjs").read_text(encoding="utf-8")
    block = text.split("export const FILES = {")[1].split("};")[0]
    names = [line.split("'")[1] for line in block.splitlines() if line.strip().startswith("'")]
    assert sorted(names) == sorted(fs.BOT_REQUIRED)


def test_a_good_bot_bundle_is_fetched_and_the_manifest_written_last(tmp_path):
    served = bot_bundle()
    m = fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(served))
    assert m["version"] == "v1"
    for path, data in served.items():
        assert (tmp_path / "bot" / path).read_bytes() == data


def test_a_bundle_missing_a_required_file_is_refused(tmp_path):
    with pytest.raises(fs.FetchError, match="lacks required files: shrunk_int8.bin"):
        fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(bot_bundle(drop="shrunk_int8.bin")))
    assert not (tmp_path / "bot" / "bot_files.json").exists()


def test_a_missing_chunk_is_refused(tmp_path):
    served = bot_bundle()
    del served["shrunk_int8.bin.001"]
    with pytest.raises(fs.FetchError, match="404"):
        fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(served))


def test_a_changed_chunk_is_refused(tmp_path):
    served = bot_bundle()
    served["vocab.txt.000"] = b"tampered"
    with pytest.raises(fs.FetchError, match="sha256"):
        fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(served))


@pytest.mark.parametrize("bad", ["../x.000", "a/x.000", "vocab.txt.0", "other.bin.000", "/vocab.txt.000"])
def test_a_bad_bot_path_is_refused(tmp_path, bad):
    served = bot_bundle()
    m = json.loads(served["bot_files.json"])
    m["files"]["vocab.txt"]["chunks"][0]["path"] = bad
    served["bot_files.json"] = json.dumps(m).encode()
    with pytest.raises(fs.FetchError, match="refusing bot path"):
        fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(served))


def test_sizes_that_do_not_add_up_are_refused(tmp_path):
    served = bot_bundle()
    m = json.loads(served["bot_files.json"])
    m["files"]["config.json"]["bytes"] += 1
    served["bot_files.json"] = json.dumps(m).encode()
    with pytest.raises(fs.FetchError, match="do not add up"):
        fs.fetch_bot("o/r", tmp_path, "tok", fake_bot(served))


def test_main_fetches_the_bot_bundle_too(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_SITE_READ_TOKEN", "t")
    calls = []
    monkeypatch.setattr(fs, "fetch", lambda *a, **k: {"files": [], "built_at_utc": "x"})
    monkeypatch.setattr(fs, "fetch_bot", lambda *a, **k: calls.append(1) or {"version": "v"})
    assert fs.main(["o/r", str(tmp_path)]) == 0 and calls
