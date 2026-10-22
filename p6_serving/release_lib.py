"""p6_serving/release_lib.py: turns the India release mart into the files of the public India release, behind the exit function and the licence gate.

Pure Python (rows in, files out); the Databricks notebook reads the mart and bronze names, computes the catalogue-wide ordinary words and calls build_release().
What it guarantees, each with a test:
  * only the columns named in release_spec.yml leave (a missing or extra column is an error), none is classified personal or internal, none is an image
    or ingredient-text column;
  * the text columns go through the project's exit function (silver_lib.egress.prepare_for_export) with the contributor names the caller knows, minus the
    names that are ordinary words across the WHOLE catalogue (catalogue_ordinary_names), minus a product's own owner account in its brands;
  * every file is rendered deterministically (sorted rows, LF, UTF-8) with its sha256 in release_manifest.json;
  * the data card (README.md) and the changelog (CHANGELOG.md) are generated from the release itself, so their numbers cannot drift from the data;
  * the licence gate (p5_governance/licence_gate.py) runs on the RENDERED folder as the last step, and a violation raises: nothing is published.
The contributor names are plain text read from bronze by the notebook and passed in; this module never stores or prints them.
"""
from __future__ import annotations

import csv
import decimal
import hashlib
import io
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p5_governance"))
sys.path.insert(0, str(HERE))
from silver_lib import contract as silver_contract  # noqa: E402
from silver_lib import egress, personal  # noqa: E402

import export_lib  # noqa: E402
import licence_gate  # noqa: E402

SPEC_PATH = HERE / "release_spec.yml"
MANIFEST = licence_gate.MANIFEST_NAME
FORBIDDEN_COLUMN = re.compile(r"(?i)(?:^|_)(?:images?|img|photos?|picture|ingredients?_text|ingredients_tags)(?:_|$)")


# An Indian mobile number: an optional +91 / 91 / 0 prefix, then ten digits starting 6 to 9, in one block or split 5+5, with a space or hyphen. Silver does not scrub phone shapes
# (a liberal pattern would also hit dates, lot numbers and barcodes, PRIVACY_AUDIT.md), but a PUBLIC product-grain file must not carry one in a name or brand: the value is blanked
# and counted. Digits next to the match (a 13-digit barcode, a longer number) are not a match.
PHONE_SHAPE = re.compile(r"(?<![\d.])(?:(?:\+?91|0)[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?![\d])")
PHONE_CHECKED_COLUMNS = ("product_name", "brands")


class ReleaseRefused(export_lib.ExportRefused):
    """The release must not be published."""


def load_spec(path: Path = SPEC_PATH) -> dict:
    spec = export_lib.load_spec(path)
    r = spec.get("release") or {}
    for key in ("hf_repo", "secret_scope", "data_file", "array_separator", "title", "scope_note"):
        if not r.get(key):
            raise ValueError(f"release: missing {key}")
    d = spec["datasets"]["india_products"]
    if not set(d.get("array_columns", [])) <= set(d["columns"]):
        raise ValueError("array_columns names a column that is not released")
    bad = [c for c in d["columns"] if FORBIDDEN_COLUMN.search(c)]
    if bad:
        raise ValueError(f"image or ingredient-text column(s) in the release spec: {bad}")
    return spec


def select_sql(spec: dict, schema: str) -> str:
    return export_lib.select_sql("india_products", spec, schema)


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The catalogue-wide ordinary words
# ---------------------------------------------------------------------------------------------------------------------------------------------
_WORD = re.compile(r"\w+")


def candidate_names(handles, texts) -> set[str]:
    """The names that could possibly match somewhere in `texts` (a superset of the whole-word matches).

    A name made of letters, digits, underscores, dots and hyphens can appear as a whole word only if every \\w+ piece of it is a word of the text. The pieces of
    all texts form one set, so the test is a set lookup per name instead of a substring search of 75,000 names through several megabytes.
    """
    pieces: set[str] = set()
    for t in texts:
        if isinstance(t, str):
            pieces.update(_WORD.findall(personal.normalise(t)))
    out = set()
    for h in handles:
        parts = _WORD.findall(h)
        if parts and all(p in pieces for p in parts):
            out.add(h)
    return out


def catalogue_ordinary_names(catalogue_rows: list[dict], handles, c: dict | None = None) -> set[str]:
    """Names (8+ characters) that are whole words in the text of at least `ordinary_word_min_products` products of the WHOLE catalogue.

    catalogue_rows: dicts with product_name and brands, one per product we hold (all markets). This is the exit function's own definition of an ordinary word
    (egress.ordinary_names) applied to every product instead of only the exported rows, which fixes the over-redaction on a small export and the
    inconsistency that the same name could be 'ordinary' in one release and replaced in the next.
    """
    c = c or silver_contract.load()
    eg = c["egress"]
    handles = {personal.normalise(h) for h in handles if isinstance(h, str)}
    handles = {h for h in handles if len(h) >= eg["handle_min_length"]}
    texts = [r.get(col) for r in catalogue_rows for col in ("product_name", "brands")]
    near = candidate_names(handles, texts)
    return egress.ordinary_names(catalogue_rows, ["product_name", "brands"], near, eg["handle_min_length"], eg["ordinary_word_min_products"])


# ---------------------------------------------------------------------------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------------------------------------------------------------------------
def cell(v) -> str:
    """One value as it is written in the CSV. A float is shown with at most 10 significant digits and never in exponent notation (0.07100000000000001 becomes 0.071,
    4.8e-05 becomes 0.000048): the long tails are floating-point noise from silver's unit conversions, not information."""
    if v is None:
        return ""
    if isinstance(v, bool) or isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        s = f"{v:.10g}"
        return format(decimal.Decimal(s), "f") if "e" in s.lower() else s
    return str(v)


def render_csv(rows: list[dict], columns: list[str], array_columns, sep: str) -> bytes:
    arrays = set(array_columns)
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        out = []
        for col in columns:
            v = r[col]
            if v is not None and col in arrays:
                out.append(sep.join(str(x) for x in v))
            else:
                out.append(cell(v))
        w.writerow(out)
    return buf.getvalue().encode("utf-8")


def _front_matter(spec: dict) -> str:
    return (
        "---\n"
        "license: odbl\n"
        "pretty_name: " + spec["release"]["title"] + "\n"
        "language: [en]\n"
        "tags: [open-food-facts, food, nutrition, india, barcodes]\n"
        "---\n\n"
    )


def _share(n: int, total: int) -> str:
    return "0%" if not total else f"{100.0 * n / total:.1f}%"


def release_stats(rows: list[dict], columns: list[str]) -> dict:
    total = len(rows)
    filled = {c: sum(1 for r in rows if r[c] not in (None, "", [])) for c in columns}
    return {"rows": total, "filled": filled,
            "with_nutrition": sum(1 for r in rows if r["nutrition_format"] in ("new", "legacy")),
            "with_nutriscore": sum(1 for r in rows if r["nutriscore_grade"] in ("a", "b", "c", "d", "e")),
            "with_error_flag": sum(1 for r in rows if (r["open_error_flags"] or 0) > 0)}


def data_card(spec: dict, version: str, built_at: str, stats: dict, report: dict) -> bytes:
    r, d = spec["release"], spec["datasets"]["india_products"]
    total = stats["rows"]
    sep = r["array_separator"]
    lines = [
        _front_matter(spec) + f"# {r['title']} (release {version})\n",
        " ".join(spec["attribution"].split()) + "\n",
        "## What is this?\n",
        f"A list of {total:,} packaged products sold in India, with their barcode, name, brand, pack size, nutrition values and quality flags. "
        "It is a cleaned copy of what the Open Food Facts community has entered, taken at the time stated below. "
        "It is meant for people who build apps or analyses on top of product data, and for anyone who wants to see how complete the data is.\n",
        f"Built at {built_at} UTC. One file: `{r['data_file']}` (a plain CSV, one row per product, sorted by barcode).\n",
        "## What to know before you use it\n",
        "- **Anyone can edit Open Food Facts**, so values can be missing, wrong or out of date. Many rows have only a barcode and a name. Nothing here is checked against the real pack.",
        "- **Not everything is food.** Open Food Facts users also add cosmetics, medicines, electronics and pet food, and we do not remove them. Some rows are completely empty.",
        "- **A product may have changed** on Open Food Facts since the build time. We take a daily copy and can miss edits made between two copies.",
        f"- **Lists are joined by `{sep}`** (for example several categories in one cell). An empty cell means we have no value.",
        "- **Quality flags** (`open_error_flags`, `open_warning_flags`, `open_info_flags`) are counts of the warnings that Open Food Facts' own checks raised and that were still open at our last look. "
        "A flag means the data looks inconsistent. It does not mean a value is wrong, and no flag does not mean it is right.",
        "- **`existence_status`** says what our last check found: `present_in_snapshot` (listed in a recent Open Food Facts snapshot), `confirmed_exists` (their API confirmed it), "
        "`unverified` (not checked yet; do not read it as 'exists'), `invalid_code` or `unconfirmed`. Products that Open Food Facts told us are gone, or moved to another of its databases, are left out.",
        "- **`last_modified_t`** is the time of the newest edit we saw, as a Unix timestamp (seconds since 1970).\n",
        "## What is not in it\n",
        "No pictures or picture links. No ingredient text. No names or codes of the people who edited a product. "
        "Free text (name, brand, tags) was cleaned: emails, links, social handles and Indian ID numbers were removed, known contributor usernames of eight or more letters were replaced by `‹user›`, "
        "and a name or brand that looks like an Indian mobile number was left empty. This lowers the chance that personal data remains. It cannot guarantee it: for example, "
        "a person's own name typed as a product name cannot be told apart from a real product name. If you find personal data in the file, please tell us so we can remove it.\n",
        "## The columns\n",
        "The table shows how many rows have a value in each column.\n",
        "| column | rows filled | share |", "|---|---|---|",
    ]
    for col in d["columns"]:
        n = stats["filled"][col]
        lines.append(f"| `{col}` | {n:,} | {_share(n, total)} |")
    lines += [
        "",
        f"{stats['with_nutrition']:,} products ({_share(stats['with_nutrition'], total)}) have a nutrition table, {stats['with_nutriscore']:,} ({_share(stats['with_nutriscore'], total)}) have a Nutri-Score grade, "
        f"and {stats['with_error_flag']:,} have at least one open error-level flag.\n",
        "## Licence\n",
        "The database is available under the Open Database License (ODbL 1.0): you may use and share it, you must credit Open Food Facts, and if you share a changed version of the database you must keep it under the same licence. "
        "The individual entries are under the Database Contents License. See https://opendatacommons.org/licenses/odbl/1-0/ and https://openfoodfacts.org/terms-of-use.\n",
        "## How it was made\n",
        "Built by the PackSense project from its daily copy of Open Food Facts. The numbers in this card are computed from the file itself. "
        f"What the privacy cleaning did in this release: {json.dumps({k: report[k] for k in sorted(report)})}.\n",
    ]
    return ("\n".join(lines)).encode("utf-8")


def changelog(spec: dict, version: str, built_at: str, current: list[dict], previous: list[dict] | None, previous_version: str | None) -> bytes:
    head = f"# Changelog\n\n{' '.join(spec['attribution'].split())}\n\n## Release {version} ({built_at} UTC)\n"
    if previous is None:
        body = f"\nFirst release: {len(current):,} products.\n"
    else:
        cur = {r["code"]: r for r in current}
        prev = {r["code"]: r for r in previous}
        added = sorted(set(cur) - set(prev))
        removed = sorted(set(prev) - set(cur))
        changed = sum(1 for k in set(cur) & set(prev) if cur[k] != prev[k])
        body = (f"\nCompared with release {previous_version}: {len(added):,} products added, {len(removed):,} removed, {changed:,} with at least one changed "
                f"value, {len(set(cur) & set(prev)) - changed:,} unchanged. Total now {len(cur):,}.\n")
    return (head + body).encode("utf-8")


# ---------------------------------------------------------------------------------------------------------------------------------------------
# The release
# ---------------------------------------------------------------------------------------------------------------------------------------------
def clean_rows(rows: list[dict], spec: dict, handles, ordinary_extra, brand_exempt=None, c: dict | None = None):
    """The exit function on the product rows. Returns (rows with the spec's columns, report)."""
    c = c or silver_contract.load()
    d = spec["datasets"]["india_products"]
    cols = d["columns"]
    for r in rows:
        if set(r) != set(cols):
            raise ReleaseRefused(f"a row has columns {sorted(set(r) ^ set(cols))} that differ from the spec")
    work = [{k: export_lib._clean(r[k]) for k in cols} for r in rows]
    clean, rep = egress.prepare_for_export(work, c, handles, brand_exempt=brand_exempt, ordinary_extra=ordinary_extra)
    clean = [{k: r[k] for k in cols} for r in clean]
    report = dict(rep)
    report["phone_shaped_blanked"] = 0
    for r in clean:
        for col in PHONE_CHECKED_COLUMNS:
            if isinstance(r.get(col), str) and PHONE_SHAPE.search(r[col]):
                r[col] = None
                report["phone_shaped_blanked"] += 1
    clean.sort(key=lambda r: tuple("" if r[k] is None else str(r[k]) for k in d["order_by"]))
    return clean, report


def build_release(folder: str | Path, rows: list[dict], version: str, built_at: str, handles, ordinary_extra, spec: dict | None = None,
                  brand_exempt=None, previous: list[dict] | None = None, previous_version: str | None = None,
                  today=None, c: dict | None = None) -> dict:
    """Write the release folder (data file, README.md, CHANGELOG.md, release_manifest.json), then run the licence gate on it. Raises ReleaseRefused on a violation."""
    spec = spec or load_spec()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    problems = export_lib.classification_problems(spec)
    if problems:
        raise ReleaseRefused("; ".join(problems))
    r, d = spec["release"], spec["datasets"]["india_products"]
    clean, report = clean_rows(rows, spec, handles, ordinary_extra, brand_exempt, c)
    data = render_csv(clean, d["columns"], d.get("array_columns", []), r["array_separator"])
    (folder / r["data_file"]).write_bytes(data)
    stats = release_stats(clean, d["columns"])
    card = data_card(spec, version, built_at, stats, report)
    log = changelog(spec, version, built_at, rendered_rows(clean, spec), previous, previous_version)
    (folder / "README.md").write_bytes(card)
    (folder / "CHANGELOG.md").write_bytes(log)
    files = [
        {"path": r["data_file"], "kind": "data", "rows": len(clean), "sha256": hashlib.sha256(data).hexdigest()},
        {"path": "README.md", "kind": "page", "sha256": hashlib.sha256(card).hexdigest()},
        {"path": "CHANGELOG.md", "kind": "page", "sha256": hashlib.sha256(log).hexdigest()},
    ]
    manifest = {
        "source": spec["source_name"],
        "source_dump_date": built_at[:10],
        "licence": spec["licence"],
        "attribution": " ".join(spec["attribution"].split()),
        "release_version": version,
        "built_at_utc": built_at,
        "exit_function": {"called": True, "module": "silver_lib.egress.prepare_for_export", "residue_scan": "passed"},
        "reports": {"india_products": report},
        "files": files,
    }
    (folder / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    violations = licence_gate.check_release(folder, today)
    if violations:
        raise ReleaseRefused("licence gate: " + "; ".join(violations))
    return manifest


def read_csv_rows(data: bytes) -> list[dict]:
    """The rows of a previously released CSV (for the changelog diff): strings only, compared against the new release rendered the same way."""
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


def rendered_rows(rows: list[dict], spec: dict) -> list[dict]:
    """Rows as they appear in the CSV (strings), so a new release and a previous CSV compare equal where the data is equal."""
    d, sep = spec["datasets"]["india_products"], spec["release"]["array_separator"]
    arrays = set(d.get("array_columns", []))
    out = []
    for r in rows:
        out.append({c: (sep.join(str(x) for x in r[c]) if r[c] is not None and c in arrays else cell(r[c])) for c in d["columns"]})
    return out


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
