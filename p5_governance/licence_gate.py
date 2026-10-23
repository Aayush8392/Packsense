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
  8. the rendered text is scanned again for the contract's scrub patterns (email, social link, @handle, Aadhaar, PAN, GSTIN, obfuscated email): one hit is a violation;
  10. the SHOWCASE file (the four-product walk-through, check_showcase): only the allowed keys, four products; every contributor field of a raw record holds only
     stand-in labels (`contributor-A`, ...); images are the marker; the hashed and lineage columns of the silver row are the `hidden on purpose` marker; no image URL and
     no scrub pattern in any string (a product's own barcode is left out of that scan); no `_hmac` key; a size cap.
  9. a CARD file (the product-card shards of the barcode lookup, `cards/<prefix>.csv`, and their `cards/splits.json`) has exactly the card columns, a barcode of 8 to 14
     digits, values inside their declared domains (enumerated codes, small non-negative counts, plausible Unix times), sorted unique barcodes that all belong to the
     file by the lookup rule `shard_for`, a size under the hard cap, and no free text anywhere (the barcode column is left out of the pattern re-scan, because a
     12 or 13 digit barcode looks like an Aadhaar number).

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
KINDS = {"score", "data", "page", "card", "card_index"}
# --- the product-card shards (roadmap Phase B item 12) ---------------------------------------------------------------------------------------------------
# The gate holds its own copy of what a card file may contain (it checks the RENDERED output, never the spec that produced it); a test ties it to export_spec.yml.
CARD_COLUMNS = ["code", "existence_status", "light", "things_flagged", "off_error", "off_bug", "off_warning", "off_info", "rules_checkable", "rules_failed",
                "fields_filled", "versions_kept", "last_edit_t", "first_version_edited_t", "first_period_from_seed", "in_india"]
CARD_EXISTENCE = {"unverified", "present_in_snapshot", "confirmed_exists", "confirmed_not_found", "moved_other_type", "invalid_code", "unconfirmed"}
CARD_LIGHTS = {"several_flagged", "one_flagged", "none_flagged", "not_enough_data"}
CARD_INT_RANGES = {"things_flagged": (0, 10000), "off_error": (0, 10000), "off_bug": (0, 10000), "off_warning": (0, 10000), "off_info": (0, 10000),
                   "rules_checkable": (0, 11), "rules_failed": (0, 11), "fields_filled": (0, 7), "versions_kept": (1, 1000000),
                   "last_edit_t": (946684800, 4102444800), "first_version_edited_t": (946684800, 4102444800), "first_period_from_seed": (0, 1), "in_india": (0, 1)}
CARD_CODE = re.compile(r"^\d{8,14}$")
CARD_PATH = re.compile(r"^cards/(\d{3,6})\.csv$")
CARD_INDEX_PATH = "cards/splits.json"
CARD_MAX_BYTES = 400_000          # a shard above this is refused; the builder splits a shard at about 150 KB, so this is a safety net, not the rule
CARD_BASE_DEPTH, CARD_MAX_DEPTH = 3, 6


# --- the showcase (roadmap Phase B item 12; context amendment A88) ----------------------------------------------------------------------------------------
SHOWCASE_IMAGES_MARKER = "[images removed]"
SHOWCASE_HIDDEN_MARKER = "hidden on purpose"
SHOWCASE_STAND_IN = re.compile(r"^contributor-[A-Z]{1,2}$")
SHOWCASE_PRODUCT_KEYS = ["ordinary_food", "several_flags", "long_history", "india"]
SHOWCASE_TOP_KEYS = {"version", "built_at_utc", "source", "licence", "attribution", "markers", "stand_ins", "products"}
SHOWCASE_PRODUCT_FIELDS = {"key", "code", "name", "brand", "bronze", "silver", "gold"}
SHOWCASE_GOLD_KEYS = {"product_history", "product_flag_spans", "product_nutrition_sets", "product_rule_verdicts", "mart_product_card", "mart_brand_scorecard",
                      "fct_product_change_daily", "fct_catalogue_quality_daily"}
SHOWCASE_MAX_BYTES = 1_500_000


def _strings(v):
    if isinstance(v, dict):
        for k, x in v.items():
            yield k
            yield from _strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from _strings(x)
    elif isinstance(v, str):
        yield v


def _unhidden_hmac_keys(v) -> int:
    """Keys ending in _hmac whose value is not the hidden marker (the silver row lists those columns, with the marker as their value)."""
    n = 0
    if isinstance(v, dict):
        for k, x in v.items():
            if isinstance(k, str) and k.endswith("_hmac") and x != SHOWCASE_HIDDEN_MARKER:
                n += 1
            n += _unhidden_hmac_keys(x)
    elif isinstance(v, list):
        for x in v:
            n += _unhidden_hmac_keys(x)
    return n


def check_showcase(path: str | Path, today: datetime.date | None = None) -> list[str]:
    """All violations of the committed showcase file (empty list = it passes). Reports counts and key names, never a value."""
    path = Path(path)
    if not path.is_file():
        return [f"{path.name}: not a file"]
    raw = path.read_bytes()
    if len(raw) > SHOWCASE_MAX_BYTES:
        return [f"{path.name}: larger than the {SHOWCASE_MAX_BYTES} byte cap"]
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return [f"{path.name}: not valid UTF-8 JSON"]
    out = []
    if not isinstance(doc, dict) or set(doc) != SHOWCASE_TOP_KEYS:
        return [f"{path.name}: the top-level keys must be exactly {sorted(SHOWCASE_TOP_KEYS)}"]
    out.extend(check_manifest({"source": doc["source"], "source_dump_date": str(doc["built_at_utc"])[:10], "licence": doc["licence"], "attribution": doc["attribution"],
                               "exit_function": {"called": True, "module": "showcase_lib", "residue_scan": "passed"},
                               "files": [{"path": path.name, "kind": "data"}]}, today))
    if doc["markers"] != {"images": SHOWCASE_IMAGES_MARKER, "hidden": SHOWCASE_HIDDEN_MARKER}:
        out.append("showcase: the markers must be the fixed marker texts")
    c = silver_contract.load()
    never = {x["name"] for x in c["columns"] if x.get("egress") == "never" or x.get("class") in ("hashed", "lineage")}
    products = doc["products"]
    if not isinstance(products, list) or [p.get("key") for p in products if isinstance(p, dict)] != SHOWCASE_PRODUCT_KEYS:
        return out + [f"showcase: the products must be exactly {SHOWCASE_PRODUCT_KEYS}, in that order"]
    used_labels: set[str] = set()
    codes = []
    for p in products:
        k = p["key"]
        if set(p) != SHOWCASE_PRODUCT_FIELDS:
            out.append(f"{k}: the product keys must be exactly {sorted(SHOWCASE_PRODUCT_FIELDS)}")
            continue
        if not isinstance(p["code"], str) or not CARD_CODE.match(p["code"]):
            out.append(f"{k}: code is not 8 to 14 digits")
        else:
            codes.append(p["code"])
        bronze, silver, gold = p["bronze"], p["silver"], p["gold"]
        if not isinstance(bronze, dict) or set(bronze) != {"record", "counts"} or not isinstance(bronze["record"], dict):
            out.append(f"{k}: bronze must hold exactly record and counts")
            continue
        rec = bronze["record"]
        for f in c["personal_source_fields"]:
            v = rec.get(f)
            for x in (v if isinstance(v, list) else [v]):
                if x in (None, ""):
                    continue
                if not isinstance(x, str) or not SHOWCASE_STAND_IN.match(x):
                    out.append(f"{k}: the contributor field {f} holds something other than a stand-in label")
                else:
                    used_labels.add(x)
        for f in ("images", "selected_images"):
            if rec.get(f) not in (None, "", SHOWCASE_IMAGES_MARKER):
                out.append(f"{k}: {f} must be the images marker")
        if not isinstance(silver, dict) or set(silver) != {"row", "counts"} or not isinstance(silver["row"], dict):
            out.append(f"{k}: silver must hold exactly row and counts")
        else:
            bad = sorted(n for n in never if silver["row"].get(n) != SHOWCASE_HIDDEN_MARKER)
            if bad:
                out.append(f"{k}: the hashed and lineage columns {bad} must be 'hidden on purpose'")
        if not isinstance(gold, dict) or set(gold) != SHOWCASE_GOLD_KEYS:
            out.append(f"{k}: gold must hold exactly {sorted(SHOWCASE_GOLD_KEYS)}")
    stand_ins = doc["stand_ins"]
    if not isinstance(stand_ins, list) or not all(isinstance(x, str) and SHOWCASE_STAND_IN.match(x) for x in stand_ins) or len(stand_ins) != len(set(stand_ins)):
        out.append("showcase: stand_ins must be a list of unique stand-in labels")
    elif not used_labels <= set(stand_ins):
        out.append("showcase: a stand-in label is used that the roster does not list")
    patterns = personal.compile_patterns(c)
    hits_img = hits_pat = 0
    hits_hmac = _unhidden_hmac_keys(doc)
    for s in _strings(doc):
        text = s
        for code in codes:
            text = text.replace(code, "")
        if IMAGE_URL.search(text):
            hits_img += 1
        if any(patterns[pat].search(text) for pat in RESCAN):
            hits_pat += 1
    if hits_img:
        out.append(f"showcase: {hits_img} string(s) with an image URL or image data")
    if hits_pat:
        out.append(f"showcase: {hits_pat} string(s) match a scrub pattern (email, social link, handle, Aadhaar, PAN, GSTIN)")
    if hits_hmac:
        out.append(f"showcase: {hits_hmac} key(s) end in _hmac")
    return out


def shard_for(code: str, splits) -> str:
    """The lookup rule, shared by the builder, this gate and (written out in the app) the browser: start with the first 3 digits; while that prefix is in the
    split list, take one more digit. The result is the file name (`cards/<result>.csv`)."""
    p = code[:CARD_BASE_DEPTH]
    while p in splits and len(p) < len(code):
        p = code[: len(p) + 1]
    return p
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
        scan_text = text
        if f["kind"] == "card":        # a 12 or 13 digit barcode looks like an Aadhaar number: the code column is checked by its own strict rule instead
            scan_text = "\n".join(line.split(",", 1)[1] if "," in line else "" for line in text.splitlines())
        for pat in RESCAN:
            n = len(patterns[pat].findall(scan_text))
            if n:
                out.append(f"{name}: {n} match(es) of the {pat} pattern in the rendered output")
        kind = f["kind"]
        if kind in ("card", "card_index"):
            continue                    # their own rules run once all of them are known (check_cards below)
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
    out.extend(check_cards(folder, m))
    if not attribution:
        out.append("manifest: no attribution text")
    return out


def check_cards(folder: Path, m: dict) -> list[str]:
    """The card rules (9 in the module docstring). Reads the split list first, because every row must belong to the file it is in by `shard_for`."""
    out = []
    files = [f for f in (m.get("files") or []) if isinstance(f, dict) and f.get("kind") in ("card", "card_index")]
    if not files:
        return out
    index = [f for f in files if f.get("kind") == "card_index"]
    cards = [f for f in files if f.get("kind") == "card"]
    if len(index) != 1 or index[0].get("path") != CARD_INDEX_PATH:
        return [f"cards: exactly one card_index file named {CARD_INDEX_PATH} is required"]
    splits: set[str] = set()
    try:
        obj = json.loads((folder / CARD_INDEX_PATH).read_text(encoding="utf-8"))
        listed = obj["splits"]
        if set(obj) != {"version", "splits"} or obj["version"] != 1 or not isinstance(listed, list):
            raise ValueError("shape")
        if any((not isinstance(s, str)) or not re.fullmatch(r"\d{3,5}", s) for s in listed) or listed != sorted(set(listed)):
            raise ValueError("values")
        splits = set(listed)
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{CARD_INDEX_PATH}: must be JSON with version 1 and a sorted list of unique digit prefixes of 3 to 5 digits under the key splits"]
    prefixes = set()
    for f in cards:
        name = f["path"]
        mt = CARD_PATH.match(name)
        if not mt:
            out.append(f"{name}: a card file must be named cards/<3 to 6 digits>.csv")
            continue
        prefix = mt.group(1)
        prefixes.add(prefix)
        if prefix in splits:
            out.append(f"{name}: its prefix is in the split list, so the cards belong in longer files")
        p = folder / name
        if not p.is_file():
            continue                    # the generic rule above already reported it
        if p.stat().st_size > CARD_MAX_BYTES:
            out.append(f"{name}: larger than the {CARD_MAX_BYTES} byte cap for a card file")
            continue                    # not parsed: an oversized file is refused on size alone
        reader = csv.reader(io.StringIO(p.read_text(encoding="utf-8")))
        header = next(reader, None)
        if header != CARD_COLUMNS:
            out.append(f"{name}: the columns must be exactly the card columns")
            continue
        last, bad = None, {}
        n_rows = 0
        try:
            all_rows = list(reader)
        except csv.Error:
            out.append(f"{name}: cannot be read as csv")
            continue
        for row in all_rows:
            n_rows += 1
            if len(row) != len(CARD_COLUMNS):
                bad["a row with the wrong number of fields"] = bad.get("a row with the wrong number of fields", 0) + 1
                continue
            r = dict(zip(CARD_COLUMNS, row))
            problems = []
            if not CARD_CODE.match(r["code"]):
                problems.append("code is not 8 to 14 digits")
            else:
                if shard_for(r["code"], splits) != prefix:
                    problems.append("a barcode is in a file it does not belong to")
                if last is not None and r["code"] <= last:
                    problems.append("barcodes are not sorted and unique")
                last = r["code"]
            if r["existence_status"] not in CARD_EXISTENCE:
                problems.append("existence_status outside its values")
            if r["light"] not in CARD_LIGHTS:
                problems.append("light outside its values")
            for col, (lo, hi) in CARD_INT_RANGES.items():
                v = r[col]
                if not re.fullmatch(r"\d{1,10}", v) or not lo <= int(v) <= hi:
                    problems.append(f"{col} is not an integer in {lo} to {hi}")
            if all(re.fullmatch(r"\d{1,10}", r[c]) for c in ("things_flagged", "off_error", "off_bug", "rules_checkable", "rules_failed")):
                if int(r["rules_failed"]) > int(r["rules_checkable"]) or int(r["things_flagged"]) != int(r["off_error"]) + int(r["off_bug"]) + int(r["rules_failed"]):
                    problems.append("things_flagged and the rule counts do not add up")
            for pr in problems:
                bad[pr] = bad.get(pr, 0) + 1
        if n_rows == 0:
            out.append(f"{name}: has no rows")
        for pr, n in sorted(bad.items()):
            out.append(f"{name}: {n} row(s): {pr}")        # a count, never a value
    for s in sorted(splits):
        if s in prefixes:
            continue
        if not any(q.startswith(s) and len(q) == len(s) + 1 for q in prefixes) and not any(q.startswith(s) and len(q) > len(s) for q in splits):
            out.append(f"{CARD_INDEX_PATH}: the split prefix {s} has no longer files under it")
    return out
