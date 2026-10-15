"""Extracts test fixtures for the India seed load: a few REAL bronze records that are India products, plus records where the text
"en:india" appears but India is not a country of the product. Same sanitising as extract_fixtures.py (it reuses that script's
notebook and only swaps the list of cases): identities replaced inside Databricks, images removed, emails replaced, and a proof
that no original username survives. Output: p2_lakehouse/tests/fixtures/seed_india_lines.jsonl (committed).

  python p2_lakehouse/bootstrap/extract_seed_fixtures.py --env-file PATH [--bronze-schema workspace.packsense_seed_stage] [--set legacy]
By default records come from the production bronze; after the seed has been staged, point --bronze-schema at the staging schema
to pick legacy-format India products too. Environment: DATABRICKS_HOST, DATABRICKS_TOKEN (admin). Prints counts only.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fixtures as base  # noqa: E402

SEED_CASES = r'''
 ("india_new", "raw_json LIKE '%\"en:india\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and bool(agg(d)), 2),
 ("india_no_nutrition", "raw_json LIKE '%\"en:india\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and not agg(d) and not d.get("nutriments"), 1),
 ("india_with_other_countries", "raw_json LIKE '%\"en:india\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and len(d.get("countries_tags") or []) > 1, 1),
 ("india_text_but_not_a_country", "raw_json LIKE '%en:india%'", lambda d: "en:india" in json.dumps(d) and "en:india" not in (d.get("countries_tags") or []), 2),
 ("india_legacy_nutriments", "raw_json LIKE '%\"nutriments\":{\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and isinstance(d.get("nutriments"), dict) and any(k.endswith("_100g") for k in d["nutriments"]), 3),
'''


LEGACY_CASES = r'''
 ("india_legacy_nutriments", "raw_json LIKE '%\"nutriments\":{\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and not agg(d) and isinstance(d.get("nutriments"), dict) and any(k.endswith("_100g") and k[:-5] not in ("nova-group", "nutrition-score-fr", "fruits-vegetables-nuts-estimate-from-ingredients", "fruits-vegetables-legumes-estimate-from-ingredients") for k in d["nutriments"]), 4),
 ("india_legacy_computed_keys_only", "raw_json LIKE '%\"nutriments\":{\"%'", lambda d: "en:india" in (d.get("countries_tags") or []) and not agg(d) and isinstance(d.get("nutriments"), dict) and [k for k in d["nutriments"] if k.endswith("_100g")] != [] and all(k[:-5] in ("nova-group", "nutrition-score-fr", "fruits-vegetables-nuts-estimate-from-ingredients", "fruits-vegetables-legumes-estimate-from-ingredients") for k in d["nutriments"] if k.endswith("_100g")), 2),
'''


def build_notebook(bronze_schema: str, cases: str = SEED_CASES) -> str:
    nb = base.NOTEBOOK
    head, sep, rest = nb.partition("CASES = [")
    _, sep2, tail = rest.partition("]\n\npicked = []")
    assert sep and sep2, "extract_fixtures.NOTEBOOK changed shape: update this script"
    nb = head + "CASES = [" + cases + "]\n\npicked = []" + tail
    # the two-versions-of-one-product block is for the silver history tests, not for the seed
    a, sep3, b = nb.partition("# two versions of one product")
    _, sep4, c = b.partition("# ---- sanitise")
    assert sep3 and sep4, "extract_fixtures.NOTEBOOK changed shape: update this script"
    nb = a + "# ---- sanitise" + c
    old = 'BRONZE = "workspace.packsense_bronze.bronze_delta_raw"'
    assert old in nb
    return nb.replace(old, f'BRONZE = "{bronze_schema}.bronze_delta_raw"')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", required=True)
    ap.add_argument("--bronze-schema", default="workspace.packsense_bronze")
    ap.add_argument("--set", choices=["base", "legacy"], default="base", help="legacy: only old-format India products, into seed_india_legacy.jsonl")
    args, _ = ap.parse_known_args()
    legacy = args.set == "legacy"
    base.NOTEBOOK = build_notebook(args.bronze_schema, LEGACY_CASES if legacy else SEED_CASES)
    base.OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / ("seed_india_legacy.jsonl" if legacy else "seed_india_lines.jsonl")
    sys.argv = [sys.argv[0], "--env-file", args.env_file]
    return base.main()


if __name__ == "__main__":
    sys.exit(main())
