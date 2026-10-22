"""The exit: one shared function that every export path calls before data leaves our control.

Silver itself blocks nothing on suspicion. What matters is what leaves: the public release, the public site, static score
files, LLM prompts, shared ML feature tables, logs, README and test fixtures. Each of those calls prepare_for_export().

  1. columns marked egress: never in the contract are dropped (the hashed contributor codes: OFF publishes the usernames, so a
     code can be matched to a name by joining on code and last_modified_t),
  2. the contract's scrub patterns are applied to every text value,
  3. known contributor names of the contract's length or more are replaced as whole words, EXCEPT ordinary words (a name that
     occurs in the text of 10 or more of the exported products: chocolat, carrefour...) and, when the caller says so, a
     product's own owner account in its brand,
  4. the result is scanned again and the export is refused if a pattern or a replaced name is still there.

The list of names is passed in by the caller (derived from bronze at export time) and is never stored by this module.
Names of 5 to 7 characters are not replaced: they are counted by the caller's audit, because most of them are brand words.
"""
import collections

from . import contract as contract_lib
from . import personal


class EgressRefused(Exception):
    """The scan after cleaning still found something that must not leave."""


def never_columns(c: dict) -> set:
    return {x["name"] for x in c["columns"] if x.get("egress") == "never"}


def _texts(value):
    return [value] if isinstance(value, str) else [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def ordinary_names(rows: list, text_cols: list, handles, min_length: int, min_products: int) -> set:
    """Names that appear (whole word) in the text of at least min_products different rows: treated as ordinary vocabulary."""
    rx = personal.handle_regex({h for h in handles if len(h) >= min_length})
    if rx is None:
        return set()
    df = collections.Counter()
    for row in rows:
        seen = set()
        for col in text_cols:
            for t in _texts(row.get(col)):
                seen.update(m.group(0).lower() for m in rx.finditer(t))
        df.update(seen)
    return {n for n, k in df.items() if k >= min_products}


def prepare_for_export(rows: list, c: dict, handles, brand_exempt=None, ordinary_extra=None):
    """rows: dicts of silver columns. handles: iterable of plain contributor names known to the caller.

    brand_exempt: optional {(code, last_modified_t): set of names} whose appearance in `brands` is the product's own branding.
    ordinary_extra: optional set of normalised names that are ordinary words across the WHOLE catalogue (computed by the caller over every product, not only
    the exported rows). The in-batch count alone over-redacts on a small export; this set is added to it, so the export treats a name as ordinary if EITHER says so.
    Returns (clean rows, report). Raises EgressRefused if anything that must not leave is still present.
    """
    eg = c["egress"]
    min_len = eg["handle_min_length"]
    patterns = personal.compile_patterns(c)
    text_cols = contract_lib.text_column_names(c)
    drop = never_columns(c)
    handles = {personal.normalise(h) for h in handles if isinstance(h, str)}
    long_names = {h for h in handles if len(h) >= min_len}
    ordinary = ordinary_names(rows, text_cols, long_names, min_len, eg["ordinary_word_min_products"])
    ordinary = ordinary | {personal.normalise(x) for x in (ordinary_extra or ()) if isinstance(x, str)}
    names = long_names - ordinary
    sentinel = c["own_handle_redaction"]["sentinel"]
    replacement = c["scrub"]["replacement"]
    brand_exempt = brand_exempt or {}
    report = collections.Counter()
    report["rows"] = len(rows)
    report["ordinary_names_left_alone"] = len(ordinary)
    out = []
    for row in rows:
        clean = {k: v for k, v in row.items() if k not in drop}
        report["columns_dropped"] = len(drop & set(row))
        exempt = brand_exempt.get((row.get("code"), row.get("last_modified_t")), set())
        for col in text_cols:
            if col not in clean or clean[col] is None:
                continue
            col_names = names - exempt if col == "brands" else names
            vals = []
            for t in (clean[col] if isinstance(clean[col], list) else [clean[col]]):
                if not isinstance(t, str):
                    vals.append(t)
                    continue
                t, n_pat = personal.scrub(t, patterns)
                t, n_name = personal.redact_handles(t, col_names, sentinel)
                report["patterns_removed"] += n_pat
                report["names_replaced"] += n_name
                vals.append(t)
            clean[col] = vals if isinstance(clean[col], list) else vals[0]
        out.append(clean)
    # the scan after cleaning: refuse rather than export something that slipped through
    rx_names = personal.handle_regex(names)
    for row in out:
        for col in text_cols:
            for t in _texts(row.get(col)):
                body = t.replace(sentinel, "").replace(replacement, "")
                if personal.has_pattern(body, patterns):
                    raise EgressRefused(f"a scrub pattern is still present in {col} of product {row.get('code')}")
                if rx_names is not None and col != "brands" and rx_names.search(body):
                    raise EgressRefused(f"a replaced name is still present in {col} of product {row.get('code')}")
    leftover = [k for k in drop if any(k in r for r in out)]
    if leftover:
        raise EgressRefused(f"columns marked egress: never are still present: {leftover}")
    return out, report


def _walk_strings(value, fn):
    """The same structure with fn applied to every string value (dict keys are not touched)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_walk_strings(v, fn) for v in value]
    if isinstance(value, dict):
        return {k: _walk_strings(v, fn) for k, v in value.items()}
    return value


def _all_strings(value):
    """Every string in a value, dict keys included (used by the scan after cleaning)."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for v in value:
            yield from _all_strings(v)
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _all_strings(k)
            yield from _all_strings(v)


def prepare_vocabulary_for_export(rows: list, c: dict):
    """The exit for taxonomy (vocabulary) rows: rows of silver_taxonomy_tag, or an excerpt of them, such as the comparison fixture.

    Taxonomies hold no contributor names (their properties are an allowlist, see contracts/taxonomy.yml), so there is no name list
    here. What remains of the product exit's duties: columns marked egress: never are dropped, the contract's scrub patterns are
    applied to every string value, and the result is scanned again (dict keys included): the export is refused if a pattern is
    still present. Returns (clean rows, report). The input rows are not changed."""
    patterns = personal.compile_patterns(c)
    replacement = c["scrub"]["replacement"]
    drop = never_columns(c)
    report = collections.Counter()
    report["rows"] = len(rows)

    def scrub_text(text):
        out, n = personal.scrub(text, patterns)
        report["patterns_removed"] += n
        return out

    out = []
    for row in rows:
        report["columns_dropped"] += len(drop & set(row))
        out.append({k: _walk_strings(v, scrub_text) for k, v in row.items() if k not in drop})
    for row in out:
        for text in _all_strings(list(row.values())):
            if personal.has_pattern(text.replace(replacement, ""), patterns):
                raise EgressRefused(f"a scrub pattern is still present in a vocabulary row (tag {row.get('tag')})")
    leftover = [k for k in drop if any(k in r for r in out)]
    if leftover:
        raise EgressRefused(f"columns marked egress: never are still present: {leftover}")
    return out, report


def assert_no_hashed_columns(columns, c: dict):
    """For export paths that build their own column list: refuse any column marked egress: never."""
    bad = sorted(set(columns) & never_columns(c))
    if bad:
        raise EgressRefused(f"columns marked egress: never in the export: {bad}")
