"""p6_serving/showcase_lib.py: the pure logic of the one-off showcase export (roadmap Phase B item 12; context amendment A88).

The showcase follows FOUR real products through the raw copy (bronze), the cleaned row (silver) and the gold tables, for the public "How we work" page. Everything
shown is real; the only things changed are the private parts: volunteers' usernames become labelled stand-ins (`contributor-A`, `contributor-B`, ...: the same person
gets the same label in every product), product images become a marker, and the hashed and lineage columns of silver are shown as `hidden on purpose`.

This module holds the rules with no Spark and no network (the notebook p6_serving/notebooks/showcase_export.py runs the queries and calls it), so each rule is
tested on real records. It never prints or stores a name: the notebook returns counts only, and the redacted file is read by the owner before it is committed.
The licence gate checks the committed file again (licence_gate.check_showcase) when the Pages site is built.
"""
from __future__ import annotations

import copy
import datetime as dt
import decimal
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p5_governance"))
import licence_gate as gate  # noqa: E402
from silver_lib import egress, personal  # noqa: E402

MARKER_IMAGES = gate.SHOWCASE_IMAGES_MARKER
MARKER_HIDDEN = gate.SHOWCASE_HIDDEN_MARKER
STAND_IN = gate.SHOWCASE_STAND_IN
NAME_MIN_LENGTH = 8               # the project's bound: a contributor name shorter than this is not searched for in free text (it would match ordinary words)


def label_for(index: int) -> str:
    """contributor-A ... contributor-Z, then contributor-AA, contributor-AB, ..."""
    s = ""
    n = index
    while True:
        s = chr(ord("A") + n % 26) + s
        n = n // 26 - 1
        if n < 0:
            break
    return f"contributor-{s}"


class StandIns:
    """Name -> stand-in label, assigned in order of first sight and kept for the whole export (the same person, the same label, in every product)."""

    def __init__(self):
        self.labels: dict[str, str] = {}

    def label(self, name: str) -> str:
        key = personal.normalise(name)
        if key not in self.labels:
            self.labels[key] = label_for(len(self.labels))
        return self.labels[key]

    def known(self) -> set[str]:
        return set(self.labels)

    def __len__(self) -> int:
        return len(self.labels)


def hidden_columns(c: dict) -> list[str]:
    """The silver columns shown as `hidden on purpose`: everything the contract marks never-export (the hashed contributor codes and the key version) and the
    lineage columns (internal, not public)."""
    never = egress.never_columns(c)
    return [x["name"] for x in c["columns"] if x["name"] in never or x.get("class") in ("hashed", "lineage")]


def identity_names(record: dict, c: dict) -> list[str]:
    """Every non-empty string in the record's contributor fields (the contract's personal_source_fields)."""
    return personal.personal_values(record, c["personal_source_fields"])


# ---- the raw record ---------------------------------------------------------------------------------------------------------------------------------

def _has_image_url(v) -> bool:
    return isinstance(v, str) and bool(gate.IMAGE_URL.search(v))


def _replace_names(text: str, handles: set[str], standins: StandIns, rx_cache: dict) -> tuple[str, int]:
    """Replace the known names in one string, wherever they occur inside it (not only as whole words). The exit function's whole-word rule is right for a
    public release of thousands of products, where a short name inside a longer word is usually just a word. Here four records are shown and read by their owner
    before they are committed, and the cost of missing a name is higher: a real record was found with a username as the start of an app name ('App - <name>-pro'),
    which a whole-word rule leaves in place. Names passed in are 8+ characters and exclude the words that are ordinary across the whole catalogue."""
    if not handles or not text:
        return text, 0
    if "rx" not in rx_cache:
        rx_cache["rx"] = re.compile("|".join(re.escape(h) for h in sorted(handles, key=len, reverse=True)), re.IGNORECASE)
    n = 0

    def sub(m):
        nonlocal n
        n += 1
        return standins.label(m.group(0))
    return rx_cache["rx"].sub(sub, text), n


def redact_raw(record: dict, standins: StandIns, handles: set[str], patterns: dict, c: dict) -> tuple[dict, dict]:
    """The redacted copy of one raw record and counts of what was done.

    1. every contributor field is replaced by stand-in labels (whatever the length of the name);
    2. images: the images object and every field or value that is an image URL become one marker;
    3. a known name (8+ characters, passed in WITHOUT the ordinary words) is replaced wherever it still appears, even inside a longer word or tag;
    4. the contract's scrub patterns (email, web address, social link, ...) are applied to every string, as silver does for its free text.
    Counts only: how many names, images, text hits and pattern hits."""
    rec = copy.deepcopy(record)
    counts = {"contributor_fields_replaced": 0, "image_fields_marked": 0, "names_replaced_in_text": 0, "patterns_removed": 0}
    for f in c["personal_source_fields"]:
        v = rec.get(f)
        if isinstance(v, str) and v.strip():
            rec[f] = standins.label(v)
            counts["contributor_fields_replaced"] += 1
        elif isinstance(v, list):
            rec[f] = [standins.label(x) if isinstance(x, str) and x.strip() else x for x in v]
            counts["contributor_fields_replaced"] += sum(1 for x in v if isinstance(x, str) and x.strip())
    cache: dict = {}

    def walk(v, key=None):
        if key in ("images", "selected_images") and v not in (None, "", [], {}):
            counts["image_fields_marked"] += 1
            return MARKER_IMAGES
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        if isinstance(v, str):
            if _has_image_url(v):
                counts["image_fields_marked"] += 1
                return MARKER_IMAGES
            if STAND_IN.match(v):
                return v
            v, n = _replace_names(v, handles, standins, cache)
            counts["names_replaced_in_text"] += n
            v, n = personal.scrub(v, patterns)
            counts["patterns_removed"] += n
        return v

    out = {k: (rec[k] if k in c["personal_source_fields"] else walk(v, k)) for k, v in rec.items()}
    return out, counts


def names_remaining(obj, names: set[str]) -> int:
    """How many of the given names (normalised) still occur in the object: as a whole string value, or (8+ characters) anywhere in a string. Counts only."""
    n = 0
    long_names = [x for x in names if len(x) >= NAME_MIN_LENGTH]
    rx = re.compile("|".join(re.escape(x) for x in sorted(long_names, key=len, reverse=True)), re.IGNORECASE) if long_names else None

    def walk(v):
        nonlocal n
        if isinstance(v, dict):
            for k, x in v.items():
                if personal.normalise(k) in names:
                    n += 1
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str):
            if personal.normalise(v) in names:
                n += 1
            elif rx is not None and rx.search(v):
                n += 1
    walk(obj)
    return n


# ---- the silver row ---------------------------------------------------------------------------------------------------------------------------------

def hide_silver(row: dict, c: dict) -> dict:
    """The silver row in contract order with the hidden columns replaced by the marker (also when they hold nothing: the page says 'hidden on purpose')."""
    hidden = set(hidden_columns(c))
    out = {}
    for col in c["columns"]:
        name = col["name"]
        out[name] = MARKER_HIDDEN if name in hidden else row.get(name)
    return out


def _tag_path(col: dict) -> str | None:
    src = col.get("from", "")
    return src[2:] if src.startswith("$.") and "." not in src[2:] else None


def silver_counts(raw: dict, silver_row: dict, c: dict) -> dict:
    """Real counts of what the cleaning did to this record (computed by comparing the raw record with its silver row; no value is repeated)."""
    hidden = set(hidden_columns(c))
    dropped: dict[str, int] = {}
    for col in c["columns"]:
        if col.get("tag_check") != "shape":
            continue
        path = _tag_path(col)
        r, s = raw.get(path) if path else None, silver_row.get(col["name"])
        if isinstance(r, list) and isinstance(s, list) or (isinstance(r, list) and s is None):
            d = len(r) - len(s or [])
            if d > 0:
                dropped[col["name"]] = d
    text = raw.get("ingredients_text") if isinstance(raw.get("ingredients_text"), str) else ""
    name_raw = raw.get("product_name") if isinstance(raw.get("product_name"), str) else ""
    shown = [v for k, v in silver_row.items() if k not in hidden]
    replacement = c["scrub"]["replacement"]
    sentinel = c["own_handle_redaction"]["sentinel"]
    nutrition = (raw.get("nutrition") or {}) if isinstance(raw.get("nutrition"), dict) else {}
    return {
        "raw_top_level_fields": len(raw),
        "silver_columns": len(c["columns"]),
        "silver_columns_filled": sum(1 for v in shown if v not in (None, [], {}, "")),
        "silver_columns_hidden": len(hidden),
        "tag_values_dropped_total": sum(dropped.values()),
        "tag_values_dropped_by_column": dropped,
        "ingredients_text_characters_in_raw": len(text),
        "ingredients_text_kept_in_silver": False,
        "ingredients_fingerprint_present": bool(silver_row.get("ingredients_sha256")),
        "product_name_scrubbed_or_replaced": int(name_raw != (silver_row.get("product_name") or "")) if name_raw else 0,
        "scrub_replacements_in_silver_text": sum(str(silver_row.get(k) or "").count(replacement) for k in ("product_name", "brands")),
        "own_handle_replacements_in_silver_name": str(silver_row.get("product_name") or "").count(sentinel),
        "nutrition_input_sets_in_raw": len(nutrition.get("input_sets") or []),
        "nutrition_format_in_silver": silver_row.get("nutrition_format"),
    }


# ---- plain values -----------------------------------------------------------------------------------------------------------------------------------

def plain(v):
    """A Spark or Python value as JSON-ready plain data: Decimal to int or float, date and time to ISO text, nested rows and maps walked."""
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


# ---- the whole file ---------------------------------------------------------------------------------------------------------------------------------

def assemble(products: list[dict], standins: StandIns, built_at: str, attribution: str) -> dict:
    """The committed file: four products in a fixed order, the stand-in roster (labels only), the markers and the attribution."""
    return {
        "version": 1,
        "built_at_utc": built_at,
        "source": "Open Food Facts",
        "licence": gate.LICENCE,
        "attribution": attribution,
        "markers": {"images": MARKER_IMAGES, "hidden": MARKER_HIDDEN},
        "stand_ins": [label_for(i) for i in range(len(standins))],
        "products": products,
    }
