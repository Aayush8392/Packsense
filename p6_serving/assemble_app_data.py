"""Builds the folder the app is built with (p6_serving/app/public/data) from the checked site data, the bot bundle and the public India release.

  python p6_serving/assemble_app_data.py <site_release_folder> <app_data_folder> [release_repo_id]      (default release repo: PackSense/packsense-india)

<site_release_folder> is what fetch_site_data.py produced (the CSVs, ATTRIBUTION.md, release_manifest.json, cards/ and bot/). The India release files come from the PUBLIC
dataset (no token): its manifest, the data card and the changelog are fetched and checked against the manifest, and `release/india_sample.csv` is the header and the first 10 rows of
`india_products.csv` (the whole file is downloaded and its sha256 checked, then only the sample is kept). The result is checked against ONE list of required files
(REQUIRED, BOT_REQUIRED): a missing file stops the build, so a site is never published without a part the app needs. Standard library only.
"""
import csv
import hashlib
import io
import json
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_site_data as fs  # noqa: E402

RELEASE_REPO = "PackSense/packsense-india"
SAMPLE_ROWS = 10
# What the app reads from its own data/ folder. A file the app starts to read must be added here (a test fails if the app names one that is not).
REQUIRED = (
    "ATTRIBUTION.md",
    "release_manifest.json",
    "brand_scorecard.csv",
    "change_daily.csv",
    "pipeline_health.csv",
    "quality_daily.csv",
    "site_status.csv",
    "cards/splits.json",
    "release/release_manifest.json",
    "release/CHANGELOG.md",
    "release/README.md",
    "release/india_sample.csv",
    "bot/bot_files.json",
)


class AssembleError(Exception):
    pass


def _get_release(repo: str, name: str, opener=urllib.request.urlopen) -> bytes:
    url = f"https://huggingface.co/datasets/{repo}/resolve/main/{urllib.parse.quote(name)}"
    req = urllib.request.Request(url, headers={"User-Agent": "packsense-site-build"})
    try:
        with opener(req, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raise AssembleError(f"release file {name}: HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise AssembleError(f"release file {name}: {type(e.reason).__name__}") from None


def sample_of(csv_bytes: bytes, rows: int = SAMPLE_ROWS) -> bytes:
    """The header and the first `rows` records (a quoted field with a line break stays whole)."""
    reader = csv.reader(io.StringIO(csv_bytes.decode("utf-8"), newline=""))
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    for i, row in enumerate(reader):
        if i > rows:
            break
        writer.writerow(row)
    return out.getvalue().encode("utf-8")


def fetch_release(repo: str, out: Path, opener=urllib.request.urlopen) -> dict:
    manifest_bytes = _get_release(repo, "release_manifest.json", opener)
    manifest = json.loads(manifest_bytes)
    listed = {f.get("path"): f.get("sha256") for f in manifest.get("files", [])}
    for needed in ("india_products.csv", "README.md", "CHANGELOG.md"):
        if needed not in listed:
            raise AssembleError(f"the release manifest does not list {needed}")
    got = {}
    for name in listed:
        if not fs.SAFE_PATH.match(name) or "/" in name:
            raise AssembleError(f"refusing release path {name!r}")
        data = _get_release(repo, name, opener)
        if listed[name] and hashlib.sha256(data).hexdigest() != listed[name]:
            raise AssembleError(f"release file {name}: sha256 does not match the release manifest")
        got[name] = data
    out.mkdir(parents=True, exist_ok=True)
    (out / "release_manifest.json").write_bytes(manifest_bytes)
    (out / "README.md").write_bytes(got["README.md"])
    (out / "CHANGELOG.md").write_bytes(got["CHANGELOG.md"])
    (out / "india_sample.csv").write_bytes(sample_of(got["india_products.csv"]))
    return manifest


def check_required(data: Path) -> None:
    missing = [n for n in REQUIRED if not (data / n).is_file()]
    if missing:
        raise AssembleError(f"required files are missing from the app data folder: {', '.join(missing)}")
    if not any((data / "cards").glob("*.csv")):
        raise AssembleError("the card shards are missing (cards/*.csv)")
    bot = json.loads((data / "bot" / fs.BOT_MANIFEST).read_text(encoding="utf-8"))
    for name in fs.BOT_REQUIRED:
        entry = bot.get("files", {}).get(name)
        if not entry or not entry.get("chunks"):
            raise AssembleError(f"the bot manifest lacks {name}")
        for c in entry["chunks"]:
            if not (data / "bot" / c["path"]).is_file():
                raise AssembleError(f"the bot chunk {c['path']} is missing")


def assemble(site_release: Path, data: Path, release_repo: str = RELEASE_REPO, opener=urllib.request.urlopen) -> None:
    if not site_release.is_dir():
        raise AssembleError(f"{site_release} is not a folder")
    data.mkdir(parents=True, exist_ok=True)
    shutil.copytree(site_release, data, dirs_exist_ok=True)
    fetch_release(release_repo, data / "release", opener)
    check_required(data)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    try:
        assemble(Path(argv[0]), Path(argv[1]), argv[2] if len(argv) == 3 else RELEASE_REPO)
    except (AssembleError, fs.FetchError, ValueError, OSError) as e:
        print(f"assemble failed: {e}")
        return 1
    n = sum(1 for p in Path(argv[1]).rglob("*") if p.is_file())
    print(f"app data ready: {n} files in {argv[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
