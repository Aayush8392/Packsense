"""The showcase logic (p6_serving/showcase_lib.py) and its licence-gate rules, on REAL records: the 20 real bronze records of p2_lakehouse/tests/fixtures (contributor names already
replaced there by placeholders such as user_0120, which makes them stand-ins for real usernames), run through the REAL silver transform. One rule is broken at a time."""
import copy
import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving"))
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p5_governance"))
import licence_gate as gate  # noqa: E402
import showcase_lib as sl  # noqa: E402
from silver_lib import contract, personal, transform  # noqa: E402

C = contract.load()
PATTERNS = personal.compile_patterns(C)
KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
LINEAGE = {"source_file": "openfoodfacts_products_1791094877_1791181482.json.gz", "file_sha256": "ab" * 32,
           "bronze_ingested_at": "2026-10-14T09:00:00", "silver_processed_at": "2026-10-14T09:05:00", "job_run_id": "test-run"}
CTX = transform.Context(C, KEY)
RECORDS = [json.loads(json.loads(line)["raw_json"]) if isinstance(json.loads(line)["raw_json"], str) else json.loads(line)["raw_json"]
           for line in open(ROOT / "p2_lakehouse" / "tests" / "fixtures" / "bronze_records.jsonl", encoding="utf-8")]
ATTRIBUTION = ("Contains data from Open Food Facts (https://openfoodfacts.org), available under the Open Database License "
               "(https://opendatacommons.org/licenses/odbl/1-0/).")


def silver_row(record):
    r = transform.process(json.dumps(record, ensure_ascii=False), CTX, LINEAGE)
    return r.row if r.kind == "silver" else None


def names_of(record):
    return {personal.normalise(n) for n in sl.identity_names(record, C)}


def with_names(n=4):
    """The first n real records that have contributor names."""
    out = [r for r in RECORDS if names_of(r)]
    assert len(out) >= n
    return out[:n]


# ---- stand-ins ------------------------------------------------------------------------------------------------------------------------------------

def test_labels_run_a_to_z_then_two_letters():
    assert [sl.label_for(i) for i in (0, 1, 25, 26, 27, 51, 52)] == [
        "contributor-A", "contributor-B", "contributor-Z", "contributor-AA", "contributor-AB", "contributor-AZ", "contributor-BA"]


def test_the_same_person_gets_the_same_label_in_every_product_and_case():
    s = sl.StandIns()
    a = s.label("user_0120")
    assert s.label("USER_0120") == a == "contributor-A"
    assert s.label("user_0030") == "contributor-B"
    assert len(s) == 2


# ---- the raw record -------------------------------------------------------------------------------------------------------------------------------

def test_every_contributor_field_of_a_real_record_becomes_stand_ins_and_none_of_the_names_survives():
    for rec in with_names(6):
        s = sl.StandIns()
        names = names_of(rec)
        red, counts = sl.redact_raw(rec, s, {n for n in names if len(n) >= 8}, PATTERNS, C)
        assert counts["contributor_fields_replaced"] > 0
        for f in C["personal_source_fields"]:
            for x in (red.get(f) if isinstance(red.get(f), list) else [red.get(f)]):
                assert x in (None, "") or gate.SHOWCASE_STAND_IN.match(x), f
        assert sl.names_remaining(red, names) == 0


def test_a_name_hidden_inside_a_tag_is_replaced():
    rec = copy.deepcopy(next(r for r in RECORDS if any("user_" in t for t in (r.get("data_sources_tags") or []))))
    names = names_of(rec)
    assert any(n in t.lower() for t in rec["data_sources_tags"] for n in names)       # the real record really has a name inside a tag
    red, counts = sl.redact_raw(rec, sl.StandIns(), {n for n in names if len(n) >= 8}, PATTERNS, C)
    assert counts["names_replaced_in_text"] >= 1
    assert not any(n in t.lower() for t in red["data_sources_tags"] for n in names)
    assert any(t.startswith("app-contributor-") for t in red["data_sources_tags"])


def test_a_name_in_free_text_is_replaced_even_inside_a_compound():
    rec = copy.deepcopy(with_names(1)[0])
    name = sorted(names_of(rec), key=len)[-1]
    rec["product_name"] = f"Tasty bars by {name} and App - {name}-pro"
    red, counts = sl.redact_raw(rec, sl.StandIns(), {name}, PATTERNS, C)
    assert name not in red["product_name"].lower() and red["product_name"].count("contributor-") == 2 and counts["names_replaced_in_text"] >= 2


def test_a_username_hidden_in_an_app_name_with_spaces_is_replaced():
    rec = next(r for r in RECORDS if any("user_" in str(r.get("data_sources", "")) for _ in [0]))
    names = names_of(rec)
    red, _ = sl.redact_raw(rec, sl.StandIns(), {n for n in names if len(n) >= 8}, PATTERNS, C)
    assert not any(n in red["data_sources"].lower() for n in names)


def test_a_contributor_name_used_as_an_object_key_is_renamed():
    rec = copy.deepcopy(with_names(1)[0])
    name = sorted(names_of(rec))[0]
    rec["sources_fields"] = {name: {"fields": ["a"]}, "other-key": {"fields": ["b"]}}
    s = sl.StandIns()
    red, counts = sl.redact_raw(rec, s, set(), PATTERNS, C, key_names=names_of(rec))
    assert counts["keys_renamed"] == 1
    assert list(red["sources_fields"]) == [s.label(name), "other-key"] and name not in red["sources_fields"]
    assert not [w for w in sl.names_remaining_where(red, names_of(rec)) if w[1] == "key"]       # no key is left; other places are not under test here (no text names passed)
    assert [w for w in sl.names_remaining_where(rec, names_of(rec)) if w[1] == "key"]


def test_ordinary_names_are_left_in_text_but_never_as_a_key():
    doc = {"brands": "carrefour", "note": "by carrefourshop", "carrefour": 1}
    assert sl.names_remaining(doc, {"carrefour"}, {"carrefour"}) == 1          # only the key counts
    assert sl.names_remaining({"brands": "carrefour"}, {"carrefour"}, {"carrefour"}) == 0
    assert sl.names_remaining({"brands": "carrefour"}, {"carrefour"}) == 1


def test_images_become_the_marker_and_no_image_url_survives():
    rec = copy.deepcopy(with_names(1)[0])
    rec["images"] = {"1": {"uploader": "someone", "sizes": {"100": {"h": 100}}}}
    rec["image_front_url"] = "https://images.openfoodfacts.org/images/products/123/front.jpg"
    red, counts = sl.redact_raw(rec, sl.StandIns(), set(), PATTERNS, C)
    assert red["images"] == sl.MARKER_IMAGES and red["image_front_url"] == sl.MARKER_IMAGES
    assert counts["image_fields_marked"] >= 2
    assert not [s for s in gate._strings(red) if gate.IMAGE_URL.search(s)]


def test_an_email_in_a_text_field_is_scrubbed():
    rec = copy.deepcopy(with_names(1)[0])
    rec["ingredients_text"] = "water, sugar. Contact info@example.org for questions"
    red, counts = sl.redact_raw(rec, sl.StandIns(), set(), PATTERNS, C)
    assert "info@example.org" not in red["ingredients_text"] and counts["patterns_removed"] >= 1
    assert red["ingredients_text"].startswith("water, sugar.")


def test_the_original_record_is_not_changed():
    rec = with_names(1)[0]
    before = json.dumps(rec, sort_keys=True)
    sl.redact_raw(rec, sl.StandIns(), set(), PATTERNS, C)
    assert json.dumps(rec, sort_keys=True) == before


def test_names_remaining_finds_a_planted_name():
    assert sl.names_remaining({"a": ["x", "carrierpigeon99 said hi"]}, {"carrierpigeon99"}) == 1
    assert sl.names_remaining({"a": ["x"]}, {"carrierpigeon99"}) == 0
    assert sl.names_remaining({"a": "shorty"}, {"shorty"}) == 1            # an exact value is caught whatever its length


# ---- the silver row -------------------------------------------------------------------------------------------------------------------------------

def test_hidden_columns_are_the_hashed_the_key_version_and_the_lineage_columns():
    hidden = set(sl.hidden_columns(C))
    assert {"creator_hmac", "editors_hmac", "hmac_key_version", "source_file", "file_sha256", "bronze_ingested_at", "silver_processed_at", "job_run_id"} <= hidden
    assert "product_name" not in hidden and "code" not in hidden and len(hidden) == 11 + 6 - 0 or len(hidden) >= 16


def test_a_real_silver_row_is_shown_with_every_hidden_column_marked_and_nothing_else_changed():
    rec = with_names(1)[0]
    row = silver_row(rec)
    shown = sl.hide_silver(row, C)
    assert list(shown) == [c["name"] for c in C["columns"]]
    hidden = set(sl.hidden_columns(C))
    for k, v in shown.items():
        assert v == sl.MARKER_HIDDEN if k in hidden else v == row.get(k)


def test_the_counts_of_what_the_cleaning_did_come_from_the_real_comparison():
    for rec in with_names(8):
        row = silver_row(rec)
        n = sl.silver_counts(rec, row, C)
        assert n["raw_top_level_fields"] == len(rec) and n["silver_columns"] == 81 and n["silver_columns_hidden"] >= 16
        assert n["ingredients_text_kept_in_silver"] is False
        assert n["ingredients_fingerprint_present"] == bool(row.get("ingredients_sha256"))
        assert n["tag_values_dropped_total"] == sum(n["tag_values_dropped_by_column"].values()) >= 0


def test_a_junk_tag_is_counted_as_dropped():
    rec = copy.deepcopy(with_names(1)[0])
    rec["categories_tags"] = list(rec.get("categories_tags") or []) + ["this is not a tag", "1234567890123"]
    row = silver_row(rec)
    n = sl.silver_counts(rec, row, C)
    assert n["tag_values_dropped_by_column"].get("categories_tags", 0) >= 2


# ---- the whole file and the gate ----------------------------------------------------------------------------------------------------------------

def gold_stub():
    return {k: [] for k in sorted(gate.SHOWCASE_GOLD_KEYS)}


def build(tmp_path):
    s = sl.StandIns()
    products = []
    for key, rec in zip(gate.SHOWCASE_PRODUCT_KEYS, with_names(4)):
        names = names_of(rec)
        red, counts = sl.redact_raw(rec, s, {n for n in names if len(n) >= 8}, PATTERNS, C)
        row = silver_row(rec)
        products.append({"key": key, "code": rec["code"], "name": rec.get("product_name") or "", "brand": rec.get("brands") or "",
                         "bronze": {"record": red, "counts": counts}, "silver": {"row": sl.hide_silver(row, C), "counts": sl.silver_counts(rec, row, C)},
                         "gold": gold_stub()})
    doc = sl.assemble(sl.plain(products), s, "2026-10-22T10:00:00", ATTRIBUTION)
    path = tmp_path / "showcase.json"
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return path, doc


def violations(path):
    return gate.check_showcase(path)


def write(path, doc):
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def made(tmp_path):
    return build(tmp_path)


def test_a_real_showcase_passes_the_gate(made):
    path, doc = made
    assert violations(path) == []
    assert len(doc["stand_ins"]) >= 2 and doc["products"][0]["bronze"]["record"]["code"]


def test_the_products_codes_do_not_trip_the_aadhaar_pattern(made):
    path, doc = made
    assert any(len(p["code"]) in (12, 13) for p in doc["products"])
    assert not [v for v in violations(path) if "scrub pattern" in v]


def test_a_real_name_left_in_a_contributor_field_is_refused(made):
    path, doc = made
    doc["products"][0]["bronze"]["record"]["creator"] = "user_0120"
    write(path, doc)
    assert any("contributor field creator" in v for v in violations(path))


def test_a_name_left_in_a_list_field_is_refused(made):
    path, doc = made
    rec = doc["products"][1]["bronze"]["record"]
    field = next(f for f in ("editors_tags", "informers_tags", "correctors_tags") if rec.get(f))
    rec[field] = rec[field] + ["realname1234"]
    write(path, doc)
    assert any(f"contributor field {field}" in v for v in violations(path))


def test_images_must_be_the_marker(made):
    path, doc = made
    doc["products"][0]["bronze"]["record"]["images"] = {"1": {"uploader": "x"}}
    write(path, doc)
    assert any("images must be the images marker" in v for v in violations(path))


def test_an_image_url_anywhere_is_refused(made):
    path, doc = made
    doc["products"][2]["gold"]["mart_product_card"] = [{"note": "https://images.openfoodfacts.org/images/products/1/front.jpg"}]
    write(path, doc)
    assert any("image URL" in v for v in violations(path))


def test_a_hidden_column_that_shows_a_value_is_refused(made):
    path, doc = made
    doc["products"][0]["silver"]["row"]["creator_hmac"] = "ab12cd34"
    write(path, doc)
    assert any("creator_hmac" in v and "hidden on purpose" in v for v in violations(path))


def test_an_email_anywhere_is_refused(made):
    path, doc = made
    doc["products"][3]["gold"]["product_history"] = [{"product_name": "write to person@example.org"}]
    write(path, doc)
    assert any("scrub pattern" in v for v in violations(path))


def test_a_hmac_key_anywhere_is_refused(made):
    path, doc = made
    doc["products"][0]["gold"]["product_history"] = [{"editors_hmac": 1}]
    write(path, doc)
    assert any("_hmac" in v for v in violations(path))


def test_the_products_and_keys_are_fixed(made):
    path, doc = made
    doc["products"] = doc["products"][:3]
    write(path, doc)
    assert any("products must be exactly" in v for v in violations(path))
    path2 = path.parent / "b.json"
    doc2 = build(path.parent)[1]
    doc2["extra"] = 1
    write(path2, doc2)
    assert any("top-level keys" in v for v in violations(path2))


def test_a_stand_in_missing_from_the_roster_is_refused(made):
    path, doc = made
    doc["stand_ins"] = doc["stand_ins"][:1]
    write(path, doc)
    assert any("roster" in v for v in violations(path))


def test_an_oversized_file_is_refused(made):
    path, doc = made
    doc["products"][0]["gold"]["product_history"] = [{"x": "y" * 2_000_000}]
    write(path, doc)
    assert any("byte cap" in v for v in violations(path))


def test_the_assembled_file_has_only_labels_in_its_roster(made):
    _, doc = made
    assert all(gate.SHOWCASE_STAND_IN.match(x) for x in doc["stand_ins"])
