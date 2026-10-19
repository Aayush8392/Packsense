"""The licence gate (P5 step 6): a check that runs on the RENDERED output of an export (a release folder), never on the spec that produced it.

Rules, from the design (6.7, 9) and Open Food Facts' own pages (terms of use and data page, read 2026-10-19: the database is under the ODbL 1.0, its
contents under the DbCL 1.0, product images under CC BY-SA with other rights possibly attached; reusers must "attribute the authorship to Open Food Facts" with a
link, mention the licence and link to the ODbL, and the page's example wording is "Contains data from Open Food Facts, available under the Open Database License"):

  1. the release manifest names the source, a source dump date (not in the future), the licence ODbL-1.0 and an attribution text that says Open Food Facts and
     the Open Database License and links both (https://openfoodfacts.org and the ODbL text);
  2. the export went through the exit function and its residue scan passed (the manifest says so);
  3. NO product images: no image column or field, no image URL, anywhere in any file;
  4. a score file holds only barcode, score and provenance (serving more product fields would make it a Produced Work with wider notice duties);
  5. a data file holds no column that the classification marks personal or internal (hashed contributor codes, lineage), and no `_hmac` column;
  6. a page (html, md, txt) carries the attribution itself;
  7. every listed file exists, and when the manifest gives a sha256 it matches;
  8. the rendered text is scanned again for the contract's scrub patterns (email, social link, @handle, Aadhaar, PAN, GSTIN, obfuscated email): one hit is a violation.

It returns violations as text and never repeats a matched value (a hit is reported as a count and a pattern name). NOT WIRED into a real export yet: no export exists until P6,
which must call check_release() as the last step before publishing and fail the run on any violation. This module is the gate; the wiring is P6's job."""
from __future__ import annotations

import csv
import datetime
import hashlib
import io
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "p2_lakehouse"))
sys.path.insert(0, str(HERE))
import classification_lib as cl  # noqa: E402
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import personal  # noqa: E402

MANIFEST_NAME = "release_manifest.json"
SCORE_KEYS = {"barcode", "score", "provenance"}
REQUIRED_SCORE_KEYS = {"barcode", "score", "provenance"}
KINDS = {"score", "data", "page"}
ATTRIBUTION_PHRASES = ("Open Food Facts", "Open Database License")
OFF_LINK = "openfoodfacts.org"
ODBL_LINK = "opendatacommons.org/licenses/odbl"
LICENCE = "ODbL-1.0"
IMAGE_URL = re.compile(r"(?i)(?:images|static)\.openfoodfacts\.org|\.(?:jpe?g|png|gif|webp|avif|svg)(?=$|[\s\"'?#)>,;])|data:image/")
IMAGE_FIELD = re.compile(r"(?i)^(?:images?|img|photos?|pictures?|selected_images|image_\w+|\w+_image(?:_\w+)?|\w+_images)$")
TEXT_SUFFIXES = {".html", ".htm", ".md", ".txt"}
# the generic url pattern is not used for the re-scan: the attribution itself contains links
RESCAN = tuple(n for n in personal.SCRUB_ORDER if n != "url")


def _read_rows(path: Path):
    """(rows as list of dicts or None, column names or None) for json, jsonl and csv files."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return rows, list(reader.fieldnames or [])
    if suffix == ".jsonl":
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif suffix == ".json":
        obj = json.loads(text)
        rows = obj["rows"] if isinstance(obj, dict) and "rows" in obj else obj
    else:
        return None, None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("expected a list of objects")
    cols = sorted({k for r in rows for k in r})
    return rows, cols


def _forbidden_data_columns() -> set[str]:
    spec = cl.load_spec()
    return {r["column"] for r in cl.silver_rows(spec) if r["class"] in ("personal", "internal")}


def check_manifest(m: dict, today: datetime.date | None = None) -> list[str]:
    today = today or datetime.date.today()
    out = []
    if m.get("source") != "Open Food Facts":
        out.append("manifest: source must be exactly 'Open Food Facts'")
    try:
        d = datetime.date.fromisoformat(str(m.get("source_dump_date")))
        if d > today:
            out.append("manifest: source_dump_date is in the future")
    except ValueError:
        out.append("manifest: source_dump_date must be an ISO date (YYYY-MM-DD)")
    if m.get("licence") != LICENCE:
        out.append(f"manifest: licence must be {LICENCE}")
    a = m.get("attribution")
    if not isinstance(a, str) or not all(p in a for p in ATTRIBUTION_PHRASES):
        out.append("manifest: attribution must say Open Food Facts and the Open Database License")
    elif OFF_LINK not in a or ODBL_LINK not in a:
        out.append("manifest: attribution must link Open Food Facts and the ODbL text")
    ef = m.get("exit_function") or {}
    if ef.get("called") is not True or ef.get("residue_scan") != "passed" or not ef.get("module"):
        out.append("manifest: exit_function must say it was called, which module, and that the residue scan passed")
    files = m.get("files")
    if not isinstance(files, list) or not files:
        out.append("manifest: files must list at least one file")
    else:
        for f in files:
            if not isinstance(f, dict) or not f.get("path") or f.get("kind") not in KINDS:
                out.append(f"manifest: every file needs a path and a kind in {sorted(KINDS)}")
    return out


def check_release(folder: str | Path, today: datetime.date | None = None) -> list[str]:
    """All violations of a release folder (empty list = the gate passes)."""
    folder = Path(folder)
    mpath = folder / MANIFEST_NAME
    if not mpath.exists():
        return [f"no {MANIFEST_NAME} in the folder"]
    try:
        m = json.loads(mpath.read_text(encoding="utf-8"))
    except ValueError:
        return [f"{MANIFEST_NAME} is not valid JSON"]
    out = check_manifest(m, today)
    forbidden = _forbidden_data_columns()
    patterns = personal.compile_patterns(silver_contract.load())
    attribution = m.get("attribution") if isinstance(m.get("attribution"), str) else ""
    for f in (m.get("files") or []):
        if not isinstance(f, dict) or not f.get("path") or f.get("kind") not in KINDS:
            continue
        p = folder / f["path"]
        name = f["path"]
        if not p.is_file() or folder.resolve() not in p.resolve().parents:
            out.append(f"{name}: listed in the manifest but not a file inside the release folder")
            continue
        raw = p.read_bytes()
        if f.get("sha256") and hashlib.sha256(raw).hexdigest() != f["sha256"]:
            out.append(f"{name}: sha256 does not match the manifest")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            out.append(f"{name}: not UTF-8 text, cannot be checked (binary files are not allowed in a release)")
            continue
        if IMAGE_URL.search(text):
            out.append(f"{name}: contains an image URL or image data (no product images in any public output)")
        for pat in RESCAN:
            n = len(patterns[pat].findall(text))
            if n:
                out.append(f"{name}: {n} match(es) of the {pat} pattern in the rendered output")
        kind = f["kind"]
        if kind == "page":
            if p.suffix.lower() not in TEXT_SUFFIXES:
                out.append(f"{name}: a page must be html, md or txt")
            if not all(x in text for x in ATTRIBUTION_PHRASES) or OFF_LINK not in text or ODBL_LINK not in text:
                out.append(f"{name}: the page does not carry the Open Food Facts attribution and the ODbL link")
            continue
        try:
            rows, cols = _read_rows(p)
        except ValueError as e:
            out.append(f"{name}: cannot be read as rows ({e})")
            continue
        if rows is None:
            out.append(f"{name}: a {kind} file must be json, jsonl or csv")
            continue
        if not rows:
            out.append(f"{name}: has no rows")
        bad_img = sorted(c for c in cols if IMAGE_FIELD.match(c))
        if bad_img:
            out.append(f"{name}: image column(s) {bad_img}")
        if kind == "score":
            extra = sorted(set(cols) - SCORE_KEYS)
            missing = sorted(REQUIRED_SCORE_KEYS - set(cols))
            if extra:
                out.append(f"{name}: a score file may hold only barcode, score and provenance; extra: {extra}")
            if missing:
                out.append(f"{name}: a score file needs barcode, score and provenance; missing: {missing}")
            if rows and any(not str(r.get("provenance", "")).strip() for r in rows):
                out.append(f"{name}: a row has an empty provenance")
        else:
            hit = sorted(c for c in cols if c in forbidden or c.endswith("_hmac"))
            if hit:
                out.append(f"{name}: column(s) {hit} are personal or internal and must not be exported")
    if not attribution:
        out.append("manifest: no attribution text")
    return out
