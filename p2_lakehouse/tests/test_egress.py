"""The exit function: what leaves our control is dropped, scrubbed, name-replaced and re-scanned.

Silver rows come from the real fixtures; the contributor names are the fixtures' placeholders (user_00001 ...).
"""
import copy
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from silver_lib import contract, egress, personal, run, transform  # noqa: E402

KEY = "test-key-not-a-secret-0000000000000000000000000000000000"
C = contract.load()
SENTINEL = C["own_handle_redaction"]["sentinel"]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bronze_records.jsonl"


def silver_rows(extra=()):
    rows = []
    for line in open(FIXTURES, encoding="utf-8"):
        raw = json.loads(line)["raw_json"]
        d = json.loads(raw)
        rows.append({"code": d.get("code"), "last_modified_t": d.get("last_modified_t"), "raw_json": raw, "source_file": "f",
                     "file_sha256": "ab" * 32, "ingested_at": dt.datetime(2026, 10, 14)})
    for d in extra:
        rows.append({"code": d["code"], "last_modified_t": d["last_modified_t"], "raw_json": json.dumps(d), "source_file": "f",
                     "file_sha256": "ab" * 32, "ingested_at": dt.datetime(2026, 10, 14)})
    return run.process_batch(rows, transform.Context(C, KEY), "r", dt.datetime(2026, 10, 15)).silver


def product(i, name, brands="Some Brand"):
    d = json.loads(next(json.loads(line)["raw_json"] for line in open(FIXTURES, encoding="utf-8") if json.loads(line)["case"] == "normal_new"))
    d.update(code=f"90000000{i:05d}", last_modified_t=1791300000 + i, product_name=name, brands=brands)
    return d


def test_hashed_columns_never_leave():
    out, report = egress.prepare_for_export(silver_rows(), C, handles=[])
    banned = egress.never_columns(C)
    assert banned and all(not (banned & set(r)) for r in out) and report["columns_dropped"] == len(banned)
    assert "creator_hmac" in silver_rows()[0]                   # they exist in silver, they just do not exit


def test_an_export_path_that_builds_its_own_column_list_is_refused_if_it_names_a_hashed_column():
    with pytest.raises(egress.EgressRefused, match="egress: never"):
        egress.assert_no_hashed_columns(["code", "product_name", "creator_hmac"], C)
    egress.assert_no_hashed_columns(["code", "product_name", "brands"], C)


def test_patterns_are_scrubbed_in_every_text_value_including_tags():
    rows = silver_rows([product(1, "Biscuits")])
    # values that reach an export path after silver (silver itself already scrubs product_name and brands)
    rows[-1]["product_name"] = "Biscuits www.example.com"
    rows[-1]["categories_tags"] = ["en:milk", "en:x@example.org"]
    out, report = egress.prepare_for_export(rows, C, handles=[])
    assert out[-1]["product_name"] == "Biscuits [removed]" and out[-1]["categories_tags"] == ["en:milk", "en:[removed]"] and report["patterns_removed"] >= 2


def test_a_known_name_of_eight_or_more_characters_is_replaced_as_a_whole_word():
    rows = silver_rows([product(1, "Cake by user_00077 bakery")])
    out, report = egress.prepare_for_export(rows, C, handles={"user_00077"})
    assert out[-1]["product_name"] == f"Cake by {SENTINEL} bakery" and report["names_replaced"] == 1


def test_names_shorter_than_the_threshold_are_left_alone():
    rows = silver_rows([product(1, "Cake by abcdefg")])
    assert egress.prepare_for_export(rows, C, handles={"abcdefg"})[0][-1]["product_name"] == "Cake by abcdefg"


def test_ordinary_words_that_are_also_names_are_left_alone():
    extra = [product(i, "Chocolatier noir") for i in range(1, 13)] + [product(20, "Rare user_00077 cake")]
    out, report = egress.prepare_for_export(silver_rows(extra), C, handles={"chocolatier", "user_00077"})
    names = [r["product_name"] for r in out if r["code"].startswith("90000000")]
    assert names.count("Chocolatier noir") == 12 and f"Rare {SENTINEL} cake" in names
    assert report["ordinary_names_left_alone"] == 1 and report["names_replaced"] == 1


def test_a_name_that_is_the_products_own_brand_account_can_be_kept_in_brands_only():
    rows = silver_rows([product(1, "Cake user_00088", brands="user_00088 foods")])
    code = rows[-1]["code"]
    strict, _ = egress.prepare_for_export(rows, C, handles={"user_00088"})
    assert strict[-1]["brands"] == f"{SENTINEL} foods" and strict[-1]["product_name"] == f"Cake {SENTINEL}"
    keep, _ = egress.prepare_for_export(rows, C, handles={"user_00088"}, brand_exempt={(code, rows[-1]["last_modified_t"]): {"user_00088"}})
    assert keep[-1]["brands"] == "user_00088 foods" and keep[-1]["product_name"] == f"Cake {SENTINEL}"


def test_the_input_rows_are_not_changed():
    rows = silver_rows([product(1, "Cake by user_00077")])
    before = copy.deepcopy(rows)
    egress.prepare_for_export(rows, C, handles={"user_00077"})
    assert rows == before


def test_the_export_is_refused_when_the_scan_after_cleaning_still_finds_a_pattern(monkeypatch):
    rows = silver_rows([product(1, "Biscuits")])
    rows[-1]["product_name"] = "Biscuits www.example.com"
    monkeypatch.setattr(egress.personal, "scrub", lambda text, patterns: (text, 0))       # a broken scrubber
    with pytest.raises(egress.EgressRefused, match="scrub pattern"):
        egress.prepare_for_export(rows, C, handles=[])


def test_the_export_is_refused_when_a_replaced_name_is_still_present(monkeypatch):
    rows = silver_rows([product(1, "Cake user_00077")])
    monkeypatch.setattr(egress.personal, "redact_handles", lambda text, names, sentinel: (text, 0))   # a broken redactor
    with pytest.raises(egress.EgressRefused, match="replaced name"):
        egress.prepare_for_export(rows, C, handles={"user_00077"})


def test_the_names_list_is_not_kept_by_the_module():
    egress.prepare_for_export(silver_rows([product(1, "Cake user_00077")]), C, handles={"user_00077"})
    assert not any(isinstance(v, (set, frozenset, list, dict)) and "user_00077" in str(v)
                   for k, v in vars(egress).items() if not k.startswith("__"))


def test_the_report_counts_rows_and_what_was_done():
    rows = silver_rows([product(1, "Cake user_00077")])
    rows[-1]["product_name"] = "Cake user_00077 www.example.com"
    _, report = egress.prepare_for_export(rows, C, handles={"user_00077"})
    assert report["rows"] == len(rows) and report["patterns_removed"] >= 1 and report["names_replaced"] == 1
