"""assemble_app_data.py: the required-file list, the India release fetch (fake opener) and the sample cut."""
import csv
import hashlib
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import assemble_app_data as aa  # noqa: E402
import fetch_site_data as fs  # noqa: E402

APP_SRC = Path(__file__).resolve().parents[1] / "app" / "src"


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def india_files(rows=30):
    csvtext = "code,name\n" + "".join(f'{i},"n {i}\nline"\n' for i in range(rows))
    files = {"india_products.csv": csvtext.encode(), "README.md": b"card", "CHANGELOG.md": b"log"}
    manifest = {"files": [{"path": k, "sha256": hashlib.sha256(v).hexdigest()} for k, v in files.items()]}
    return {**files, "release_manifest.json": json.dumps(manifest).encode()}


def fake_release(files):
    def opener(req, timeout=0):
        name = req.full_url.rsplit("/resolve/main/", 1)[-1]
        if name not in files:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return Resp(files[name])
    return opener


def site_folder(root: Path, skip=None):
    names = [n for n in aa.REQUIRED if not n.startswith("release/") and n != "bot/bot_files.json"]
    for n in names:
        if n != skip:
            (root / n).parent.mkdir(parents=True, exist_ok=True)
            (root / n).write_text("x", encoding="utf-8")
    (root / "cards").mkdir(exist_ok=True)
    (root / "cards" / "000.csv").write_text("x", encoding="utf-8")
    (root / "bot").mkdir()
    files = {}
    for name in fs.BOT_REQUIRED:
        (root / "bot" / f"{name}.000").write_bytes(b"x")
        files[name] = {"chunks": [{"path": f"{name}.000"}]}
    if skip != "bot/bot_files.json":
        (root / "bot" / "bot_files.json").write_text(json.dumps({"files": files}), encoding="utf-8")
    return root


def test_a_complete_input_assembles(tmp_path):
    site, out = site_folder(tmp_path / "s"), tmp_path / "o"
    aa.assemble(site, out, "o/r", fake_release(india_files()))
    for n in aa.REQUIRED:
        assert (out / n).is_file()


def test_the_committed_showcase_file_is_copied_into_the_app_data_folder(tmp_path):
    """The page 'How PackSense works' reads data/showcase.json. It is committed, not on Hugging Face, so the build has to copy it (it did not, and the live page showed no tables)."""
    site, out = site_folder(tmp_path / "s"), tmp_path / "o"
    aa.assemble(site, out, "o/r", fake_release(india_files()))
    assert (out / "showcase.json").read_bytes() == aa.SHOWCASE.read_bytes()
    assert b"x" != (out / "showcase.json").read_bytes()  # not the stand-in 'x' that site_folder writes


def test_a_missing_committed_showcase_file_stops_the_build(tmp_path):
    site = site_folder(tmp_path / "s")
    with pytest.raises(aa.AssembleError, match="showcase"):
        aa.assemble(site, tmp_path / "o", "o/r", fake_release(india_files()), showcase=tmp_path / "none.json")


def test_the_sample_is_the_header_and_ten_whole_records(tmp_path):
    site, out = site_folder(tmp_path / "s"), tmp_path / "o"
    aa.assemble(site, out, "o/r", fake_release(india_files()))
    text = (out / "release" / "india_sample.csv").read_text(encoding="utf-8")
    assert text.startswith("code,name\n0,") and '"n 9\nline"' in text and "\n10," not in text
    assert len(list(csv.reader(io.StringIO(text)))) == 11


@pytest.mark.parametrize("missing", ["brand_scorecard.csv", "cards/splits.json", "ATTRIBUTION.md", "bot/bot_files.json"])
def test_a_required_file_that_is_not_in_the_input_stops_the_build(tmp_path, missing):
    site = site_folder(tmp_path / "s", skip=missing)
    with pytest.raises(aa.AssembleError, match="missing"):
        aa.assemble(site, tmp_path / "o", "o/r", fake_release(india_files()))


def test_a_missing_bot_chunk_stops_the_build(tmp_path):
    site = site_folder(tmp_path / "s")
    (site / "bot" / "shrunk_int8.bin.000").unlink()
    with pytest.raises(aa.AssembleError, match="shrunk_int8.bin.000"):
        aa.assemble(site, tmp_path / "o", "o/r", fake_release(india_files()))


def test_a_changed_release_file_is_refused(tmp_path):
    files = india_files()
    files["README.md"] = b"changed"
    with pytest.raises(aa.AssembleError, match="sha256"):
        aa.fetch_release("o/r", tmp_path, fake_release(files))


def test_a_release_that_lacks_the_data_card_is_refused(tmp_path):
    files = india_files()
    m = json.loads(files["release_manifest.json"])
    m["files"] = [f for f in m["files"] if f["path"] != "README.md"]
    files["release_manifest.json"] = json.dumps(m).encode()
    with pytest.raises(aa.AssembleError, match="README.md"):
        aa.fetch_release("o/r", tmp_path, fake_release(files))


def test_every_data_file_the_app_names_is_in_the_required_list():
    """A data file the app reads that is not in REQUIRED would silently be absent on the live site."""
    named = set()
    for p in APP_SRC.rglob("*.ts*"):
        if ".test." in p.name or "fixtures" in p.parts:
            continue
        named |= set(re.findall(r"['\"]([a-z_]+\.csv)['\"]", p.read_text(encoding="utf-8")))
        named |= set(re.findall(r"(?:dataUrl|fetchRequired|fetchOptional|fetchText)\(\s*['\"]([\w./-]+\.(?:csv|json|md))['\"]", p.read_text(encoding="utf-8")))
    assert named, "the pattern found no file names: the test needs updating"
    assert named <= set(aa.REQUIRED), sorted(named - set(aa.REQUIRED))


def test_main_returns_1_and_names_the_problem(tmp_path, capsys):
    assert aa.main([str(tmp_path / "none"), str(tmp_path / "o")]) == 1
    assert "assemble failed" in capsys.readouterr().out
