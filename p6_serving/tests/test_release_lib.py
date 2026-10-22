"""p6_serving/release_lib.py on the real rows of the India release mart (tests/fixtures/india_release_rows.json, dumped from the DuckDB fixture build):
the column rule, the exit function with the catalogue-wide ordinary words, deterministic files, the generated data card and changelog, and the licence gate
as the last step. Edge cases are made by changing one field of a real row, never by inventing a product."""
import copy
import csv
import hashlib
import io
import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving"))
import release_lib as rl  # noqa: E402

ROWS = json.loads((HERE / "fixtures" / "india_release_rows.json").read_text(encoding="utf-8"))
SPEC = rl.load_spec()
COLS = SPEC["datasets"]["india_products"]["columns"]
BUILT = "2026-10-22T08:00:00"


def build(tmp_path, rows=None, handles=(), extra=(), **kw):
    return rl.build_release(tmp_path, copy.deepcopy(rows if rows is not None else ROWS), "v1", BUILT, handles, extra, SPEC, **kw)


def csv_rows(tmp_path):
    return list(csv.DictReader(io.StringIO((tmp_path / SPEC["release"]["data_file"]).read_text(encoding="utf-8"))))


def test_the_spec_exports_only_columns_the_mart_has_and_the_classification_calls_public():
    assert rl.export_lib.classification_problems(SPEC) == []
    gold = json.loads((ROOT / "p5_governance" / "gold_columns.json").read_text(encoding="utf-8"))
    assert set(COLS) <= set(gold["models"]["mart_india_release"])
    assert set(ROWS[0]) == set(COLS)


def test_no_image_ingredient_text_or_hashed_column_can_be_listed(tmp_path):
    for bad in ("image_url", "ingredients_text", "ingredients_tags", "photos"):
        spec = yaml.safe_load((ROOT / "p6_serving" / "release_spec.yml").read_text(encoding="utf-8"))
        spec["datasets"]["india_products"]["columns"].append(bad)
        p = tmp_path / "bad_spec.yml"
        p.write_text(yaml.safe_dump(spec), encoding="utf-8")
        with pytest.raises(ValueError):
            rl.load_spec(p)
    from silver_lib import contract, egress
    never = egress.never_columns(contract.load())
    assert not never & set(COLS)


def test_the_release_builds_passes_the_gate_and_lists_every_file(tmp_path):
    m = build(tmp_path)
    rows = csv_rows(tmp_path)
    assert len(rows) == len(ROWS)
    assert [r["code"] for r in rows] == sorted(r["code"] for r in ROWS)
    assert {f["path"] for f in m["files"]} == {"india_products.csv", "README.md", "CHANGELOG.md"}
    assert rl.licence_gate.check_release(tmp_path) == []
    for f in m["files"]:
        assert hashlib.sha256((tmp_path / f["path"]).read_bytes()).hexdigest() == f["sha256"]


def test_tag_lists_are_joined_and_nulls_are_empty(tmp_path):
    build(tmp_path)
    got = {r["code"]: r for r in csv_rows(tmp_path)}
    for src in ROWS:
        out = got[src["code"]]
        assert out["categories_tags"] == "|".join(src["categories_tags"] or [])
        for c in ("brands", "energy_kcal"):
            if src[c] is None:
                assert out[c] == ""


def test_a_second_build_is_byte_identical(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ma, mb = build(a), build(b)
    assert [f["sha256"] for f in ma["files"]] == [f["sha256"] for f in mb["files"]]


def test_a_row_with_an_extra_or_missing_column_is_refused(tmp_path):
    rows = copy.deepcopy(ROWS)
    rows[0]["distinct_editors"] = 3
    with pytest.raises(rl.ReleaseRefused):
        build(tmp_path, rows)
    rows = copy.deepcopy(ROWS)
    del rows[0]["salt"]
    with pytest.raises(rl.ReleaseRefused):
        build(tmp_path / "x", rows)


def test_the_exit_scrubs_a_link_planted_in_a_real_product_name(tmp_path):
    rows = copy.deepcopy(ROWS)
    rows[2]["product_name"] = rows[2]["product_name"] + " see https://shop.example.com/p?id=1 or write to someone@example.com"
    build(tmp_path, rows)
    text = (tmp_path / "india_products.csv").read_text(encoding="utf-8")
    assert "example.com" not in text and "someone@" not in text


def test_a_name_that_is_ordinary_across_the_catalogue_is_kept_but_replaced_otherwise(tmp_path):
    # 'aashirvaad' is a real brand in the fixture; treat it as a known contributor name (8+ characters)
    handles = {"aashirvaad"}
    sentinel = rl.silver_contract.load()["own_handle_redaction"]["sentinel"]
    build(tmp_path / "plain", handles=handles)
    assert any(sentinel in (r["brands"] or "") for r in csv_rows(tmp_path / "plain")), "without the catalogue-wide set the name is replaced (rare in the export)"
    build(tmp_path / "wide", handles=handles, extra={"aashirvaad"})
    kept = [r["brands"] for r in csv_rows(tmp_path / "wide") if "aashirvaad" in (r["brands"] or "").lower()]
    assert kept and all(sentinel not in b for b in kept)


def test_catalogue_ordinary_names_follow_the_exit_functions_own_definition():
    word = "aashirvaad"
    base = next(r for r in ROWS if (r["brands"] or "").lower() == word)
    def catalogue(n):
        out = []
        for i in range(n):
            r = copy.deepcopy(base)
            r["code"] = f"X{i}"
            out.append({"product_name": r["product_name"], "brands": r["brands"]})
        return out
    assert rl.catalogue_ordinary_names(catalogue(9), {word}) == set()
    assert rl.catalogue_ordinary_names(catalogue(10), {word}) == {word}
    assert rl.catalogue_ordinary_names(catalogue(10), {"shortone"[:7]}) == set()          # under eight characters: never a candidate


def test_candidate_names_never_lose_a_name_that_could_match():
    texts = [r["product_name"] for r in ROWS] + [r["brands"] for r in ROWS]
    blob = "\n".join(rl.personal.normalise(t) for t in texts if isinstance(t, str))
    handles = {"aashirvaad", "organic", "nonexistentname", "dr.", "haldiram�s", "chilli-vinegar", "kwality"}
    near = rl.candidate_names(handles, texts)
    assert {h for h in handles if h in blob and len(h) >= 1} <= near | {h for h in handles if not rl._WORD.findall(h)}
    assert "nonexistentname" not in near


def test_the_data_card_and_changelog_carry_the_attribution_and_the_real_numbers(tmp_path):
    build(tmp_path)
    card = (tmp_path / "README.md").read_text(encoding="utf-8")
    log = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    for text in (card, log):
        assert "Open Food Facts" in text and "Open Database License" in text and "openfoodfacts.org" in text
    assert f"{len(ROWS):,} packaged products" in card and "license: odbl" in card
    assert "Not everything is food" in card and "mobile number" in card
    assert "First release" in log


def test_the_changelog_counts_added_removed_and_changed_against_the_previous_csv(tmp_path):
    first = tmp_path / "v0"
    build(first)
    previous = rl.read_csv_rows((first / "india_products.csv").read_bytes())
    previous = previous[1:]                                   # one product not in the previous release
    previous[0] = dict(previous[0], proteins="999")           # one value changed
    previous.append(dict(previous[0], code="0000000000000"))  # one product removed since
    build(tmp_path / "v1", previous=previous, previous_version="v0")
    log = (tmp_path / "v1" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "1 products added, 1 removed, 1 with at least one changed value" in log


def test_a_tampered_release_fails_the_gate(tmp_path):
    build(tmp_path)
    p = tmp_path / "india_products.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("\n", "\nhttps://images.openfoodfacts.org/images/products/x/front.jpg,", 1), encoding="utf-8")
    problems = rl.licence_gate.check_release(tmp_path)
    assert any("sha256" in x for x in problems) and any("image" in x for x in problems)


def test_a_gate_violation_raises_and_nothing_is_handed_back(tmp_path):
    spec = copy.deepcopy(SPEC)
    spec["attribution"] = "Some data."          # no Open Food Facts, no licence name
    with pytest.raises(rl.ReleaseRefused):
        rl.build_release(tmp_path, copy.deepcopy(ROWS), "v1", BUILT, (), (), spec)


def test_a_phone_shaped_name_or_brand_is_blanked_and_counted_but_barcodes_and_normal_names_are_not(tmp_path):
    rows = copy.deepcopy(ROWS)
    rows[1]["product_name"] = "77395 88222"                     # a real product name from the fixture era: the 10-digit mobile shape seen in production
    rows[2]["brands"] = "+91 98765 43210"
    rows[3]["product_name"] = "8901063368675"                  # a 13-digit barcode used as a name stays
    rows[4]["product_name"] = rows[4]["product_name"] + " 500g 2024"
    m = build(tmp_path, rows)
    got = {r["code"]: r for r in csv_rows(tmp_path)}
    assert got[rows[1]["code"]]["product_name"] == "" and got[rows[2]["code"]]["brands"] == ""
    assert got[rows[3]["code"]]["product_name"] == "8901063368675"
    assert "500g 2024" in got[rows[4]["code"]]["product_name"]
    assert m["reports"]["india_products"]["phone_shaped_blanked"] == 2


def test_phone_shape_matches_the_formats_seen_and_not_longer_numbers():
    ok = ["9876543210", "98765 43210", "98765-43210", "+91 98765 43210", "+919876543210", "09876543210", "call 9876543210 now"]
    no = ["8901063368675", "12345678901234", "5876543210", "500g", "2036123/0.24", "02 FEB 2024", "98765432101"]
    assert all(rl.PHONE_SHAPE.search(x) for x in ok)
    assert not any(rl.PHONE_SHAPE.search(x) for x in no)


def test_numbers_are_written_without_float_noise_or_exponents():
    assert rl.cell(0.07100000000000001) == "0.071"
    assert rl.cell(4.8e-05) == "0.000048"
    assert rl.cell(700.0) == "700" and rl.cell(1688.4) == "1688.4" and rl.cell(0.0) == "0"
    assert rl.cell(396.89332375000004) == "396.8933238" and rl.cell(1792471579) == "1792471579" and rl.cell(None) == "" and rl.cell("x") == "x"


def test_the_csv_holds_no_exponent_numbers(tmp_path):
    rows = copy.deepcopy(ROWS)
    rows[0]["sodium"] = 4.8e-05
    build(tmp_path, rows)
    text = (tmp_path / "india_products.csv").read_text(encoding="utf-8")
    assert "e-0" not in text and "0.000048" in text
