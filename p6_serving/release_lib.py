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
def render_csv(rows: list[dict], columns: list[str], array_columns, sep: str) -> bytes:
    arrays = set(array_columns)
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(columns)
    for r in rows:
        out = []
        for col in columns:
            v = r[col]
            if v is None:
                out.append("")
            elif col in arrays:
                out.append(sep.join(str(x) for x in v))
            else:
                out.append(v)
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
    lines = [
        _front_matter(spec) + f"# {r['title']} (release {version})\n",
        " ".join(spec["attribution"].split()) + "\n",
        "## What this is\n",
        " ".join(r["scope_note"].split()) + "\n",
        f"Built at {built_at} UTC. {total:,} products. File: `{r['data_file']}` (UTF-8 CSV, one row per product, sorted by barcode; list columns are joined by `{r['array_separator']}`).\n",
        "## What is not in it\n",
        "No product images and no image links. No ingredient text (only OFF itself holds it). No contributor names or codes. No per-product editor counts. "
        "Free text (product name, brand, tags) went through a scrub for emails, links, handles, Aadhaar, PAN and GSTIN patterns and a replacement of known contributor "
        "names of eight or more characters that are not ordinary words; this lowers the chance that personal data remains, it does not guarantee it "
        "(see PRIVACY_AUDIT.md in the PackSense repository for the measured bound). Phone-number shapes are NOT scrubbed.\n",
        "## Columns\n",
        "| column | rows filled | share |", "|---|---|---|",
    ]
    for col in d["columns"]:
        n = stats["filled"][col]
        lines.append(f"| `{col}` | {n:,} | {_share(n, total)} |")
    lines += [
        "",
        f"Products with a nutrition table: {stats['with_nutrition']:,} ({_share(stats['with_nutrition'], total)}). With a Nutri-Score grade: {stats['with_nutriscore']:,} "
        f"({_share(stats['with_nutriscore'], total)}). With at least one open error-level quality flag from Open Food Facts' own checks: {stats['with_error_flag']:,}.\n",
        "`existence_status` is what our last check said: `present_in_snapshot` (listed in a weekly Open Food Facts snapshot), `confirmed_exists` (its API answered), "
        "`unverified` (no check yet; do not read it as 'exists'), `invalid_code`, `unconfirmed`. Products confirmed gone or moved to another Open * Facts database are left out. "
        "`open_*_flags` count the quality flags that Open Food Facts' own checks recorded and that were still open at our last observation; they say the data is "
        "*flagged*, not that a value is wrong or right. `last_modified_t` is the Unix time of the newest edit we saw.\n",
        "## Known limits\n",
        "- A snapshot of crowd-edited data: values may have changed on Open Food Facts since the build time, and our daily capture can miss edits made between two files.",
        "- Open Food Facts publishes one record per product per day, so same-day edits are not recoverable.",
        "- About a quarter of the quality flags are generated in code by OFF and are counted like the others.",
        f"- Exit report: {json.dumps({k: report[k] for k in sorted(report)})}.\n",
        "## Licence\n",
        "The database is available under the Open Database License (ODbL 1.0): attribute Open Food Facts, share any adapted database under the same licence, keep it open. "
        "Individual contents are under the Database Contents License. See https://opendatacommons.org/licenses/odbl/1-0/ and https://openfoodfacts.org/terms-of-use.\n",
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
    clean.sort(key=lambda r: tuple("" if r[k] is None else str(r[k]) for k in d["order_by"]))
    return clean, dict(rep)


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
        out.append({c: ("" if r[c] is None else sep.join(str(x) for x in r[c]) if c in arrays else str(r[c])) for c in d["columns"]})
    return out


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
