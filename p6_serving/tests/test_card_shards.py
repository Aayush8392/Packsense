"""The product-card shards (p6_serving/export_lib.build_card_files, the gate's card rules and the lookup rule) on REAL card rows of the DuckDB fixture build
(tests/fixtures/card_rows.json: 233 products, from mart_product_card). One rule is broken at a time; the gate must name each break."""
import copy
import csv
import io
import json
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "p6_serving"))
sys.path.insert(0, str(ROOT / "p5_governance"))
import export_lib as ex  # noqa: E402
import licence_gate as gate  # noqa: E402

CARDS = json.loads((HERE / "fixtures" / "card_rows.json").read_text(encoding="utf-8"))
SPEC = ex.load_spec()
STATUS = {"built_at_utc": "2026-10-23T08:30:00", "first_complete_day": "2026-10-01", "last_complete_day": "2026-10-15",
          "products_held_all": 233, "products_held_india": 60}
sys.path.insert(0, str(HERE))
import test_export_lib as tel  # noqa: E402

DATASETS = tel.datasets()      # the real fixture rows of the other datasets: the gate refuses an empty data file


def small_spec(limit):
    s = copy.deepcopy(SPEC)
    s["card_shards"]["split_above_bytes"] = limit
    return s


def lookup(files, code):
    """The browser's rule, written out: fetch the file the rule names, then find the barcode in it."""
    splits = set(json.loads(files[gate.CARD_INDEX_PATH])["splits"])
    prefix = gate.shard_for(code, splits)
    data = files.get(f"cards/{prefix}.csv")
    if data is None:
        return None
    for row in csv.DictReader(io.StringIO(data.decode("utf-8"))):
        if row["code"] == code:
            return row
    return None


def test_the_spec_columns_equal_the_gates_card_columns_and_are_public():
    assert SPEC["card_shards"]["columns"] == gate.CARD_COLUMNS
    assert ex.classification_problems(SPEC) == []
    assert list(CARDS[0]) and set(CARDS[0]) == set(gate.CARD_COLUMNS)


def test_the_gate_domains_equal_the_models_domains():
    schema = yaml.safe_load((ROOT / "p4_modelling" / "models" / "portable" / "schema.yml").read_text(encoding="utf-8"))
    card = next(m for m in schema["models"] if m["name"] == "mart_product_card")
    by_name = {c["name"]: c for c in card["columns"]}

    def accepted(col):
        return {v for t in by_name[col]["data_tests"] if isinstance(t, dict) for v in t["accepted_values"]["arguments"]["values"]}

    assert accepted("existence_status") == gate.CARD_EXISTENCE
    assert accepted("light") == gate.CARD_LIGHTS


def test_every_real_card_survives_the_build_and_is_found_by_the_lookup_rule():
    files, rep = ex.build_card_files(CARDS, SPEC)
    assert rep["cards_in"] == rep["cards_published"] == len(CARDS) and rep["dropped_not_a_barcode"] == 0
    for r in CARDS:
        got = lookup(files, r["code"])
        assert got is not None and {k: str(v) for k, v in r.items()} == got


def test_a_small_limit_splits_big_files_and_the_lookup_still_finds_every_card():
    files, rep = ex.build_card_files(CARDS, small_spec(1500))
    splits = json.loads(files[gate.CARD_INDEX_PATH])["splits"]
    assert splits and rep["splits"] == len(splits)
    assert any(len(p) == 3 for p in splits)
    for r in CARDS:
        assert lookup(files, r["code"]) is not None
    sizes = [len(v) for k, v in files.items() if k != gate.CARD_INDEX_PATH]
    assert max(sizes) < 1500 or any(len(k) == len("cards/") + gate.CARD_MAX_DEPTH + len(".csv") for k in files)
    # a split prefix has no file of its own
    assert all(f"cards/{p}.csv" not in files for p in splits)


def test_a_split_goes_deeper_than_one_digit_when_one_digit_is_not_enough():
    one_prefix = [dict(r, code="8901" + r["code"][4:].rjust(9, "0")[:9]) for r in CARDS[:150]]
    for i, r in enumerate(one_prefix):
        r["code"] = f"8901{i:09d}"
    files, rep = ex.build_card_files(one_prefix, small_spec(10000))
    splits = json.loads(files[gate.CARD_INDEX_PATH])["splits"]
    assert "890" in splits and "8901" in splits
    for r in one_prefix:
        assert lookup(files, r["code"]) is not None


def test_codes_that_are_not_barcodes_are_dropped_and_counted():
    junk = dict(CARDS[0], code="1" * 20)
    short = dict(CARDS[1], code="1234567")
    files, rep = ex.build_card_files(CARDS + [junk, short], SPEC)
    assert rep["dropped_not_a_barcode"] == 2 and rep["cards_published"] == len(CARDS)
    assert lookup(files, "1" * 20) is None


def test_a_row_with_an_extra_or_missing_column_is_refused():
    with pytest.raises(ex.ExportRefused):
        ex.build_card_files([dict(CARDS[0], product_name="x")], SPEC)
    with pytest.raises(ex.ExportRefused):
        ex.build_card_files([{k: v for k, v in CARDS[0].items() if k != "light"}], SPEC)


def test_a_shard_that_cannot_be_split_small_enough_is_refused():
    rows = [dict(CARDS[0], code=f"89012345{i:06d}") for i in range(30000)]
    spec = small_spec(10000)
    with pytest.raises(ex.ExportRefused):
        ex.build_card_files(rows, spec)


def test_the_build_is_deterministic_and_independent_of_input_order():
    a, _ = ex.build_card_files(CARDS, SPEC)
    b, _ = ex.build_card_files(list(reversed(CARDS)), SPEC)
    assert a == b


# ---- the licence gate on the rendered folder ---------------------------------------------------------------------------------------------------------

def release(tmp_path, spec=None, rows=None):
    return ex.build_release(tmp_path, copy.deepcopy(DATASETS), STATUS, spec or small_spec(1500), cards=rows or CARDS)


@pytest.fixture
def folder(tmp_path):
    release(tmp_path)
    return tmp_path


def violations(folder):
    return gate.check_release(folder)


def rewrite(folder, name, fn):
    """Change a rendered card file and keep the manifest's sha256 honest, so only the rule under test can fire."""
    p = folder / name
    p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8", newline="")
    m = json.loads((folder / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    import hashlib
    for f in m["files"]:
        if f["path"] == name:
            f["sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    (folder / gate.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")


def a_card_file(folder):
    return sorted(p.name for p in (folder / "cards").glob("*.csv"))[0]


def test_a_real_release_with_cards_passes_the_gate(folder):
    assert violations(folder) == []
    m = json.loads((folder / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert m["reports"]["card_shards"]["cards_published"] == len(CARDS)
    kinds = {f["kind"] for f in m["files"]}
    assert {"card", "card_index"} <= kinds


def test_barcodes_in_a_card_file_do_not_trip_the_aadhaar_pattern(folder):
    assert any(len(r["code"]) in (12, 13) for r in CARDS)
    assert not [v for v in violations(folder) if "pattern" in v]


@pytest.mark.parametrize("change,expect", [
    (lambda t: t.replace("none_flagged", "all_good", 1), "light outside its values"),
    (lambda t: t.replace("present_in_snapshot", "exists", 1), "existence_status outside its values"),
    (lambda t: t.replace(",1790", ",1790.5,x", 1) if False else t.replace("\n", "\n", 1), None),
])
def test_a_value_outside_its_domain_is_named(folder, change, expect):
    if expect is None:
        return
    name = "cards/" + a_card_file(folder)
    rewrite(folder, name, change)
    assert any(expect in v for v in violations(folder))


def test_a_changed_header_is_refused(folder):
    name = "cards/" + a_card_file(folder)
    rewrite(folder, name, lambda t: t.replace("code,", "barcode,", 1))
    assert any("columns must be exactly the card columns" in v for v in violations(folder))


def test_an_extra_text_column_is_refused(folder):
    name = "cards/" + a_card_file(folder)
    rewrite(folder, name, lambda t: "\n".join((line + (",product_name" if i == 0 else ",x")) for i, line in enumerate(t.splitlines())) + "\n")
    assert any("columns must be exactly the card columns" in v for v in violations(folder))


def test_a_card_in_the_wrong_file_is_refused(folder):
    files = sorted((folder / "cards").glob("*.csv"))
    a, b = files[0], files[-1]
    row = b.read_text(encoding="utf-8").splitlines()[1]
    rewrite(folder, "cards/" + a.name, lambda t: t + row + "\n")
    assert any("not belong" in v or "not sorted" in v for v in violations(folder))


def test_unsorted_or_duplicate_barcodes_are_refused(folder):
    name = "cards/" + a_card_file(folder)
    lines = (folder / name).read_text(encoding="utf-8").splitlines()
    rewrite(folder, name, lambda t: "\n".join([lines[0], lines[1], lines[1]] + lines[2:]) + "\n")
    assert any("not sorted and unique" in v for v in violations(folder))


def test_inconsistent_counts_are_refused(folder):
    name = "cards/" + a_card_file(folder)

    def wreck(t):
        lines = t.splitlines()
        head = lines[0].split(",")
        cells = lines[1].split(",")
        cells[head.index("rules_failed")] = "5"
        cells[head.index("rules_checkable")] = "2"
        return "\n".join([lines[0], ",".join(cells)] + lines[2:]) + "\n"

    rewrite(folder, name, wreck)
    assert any("do not add up" in v for v in violations(folder))


def test_a_huge_card_file_is_refused(folder):
    name = "cards/" + a_card_file(folder)
    rewrite(folder, name, lambda t: t + "x" * (gate.CARD_MAX_BYTES + 10))
    assert any("byte cap" in v for v in violations(folder))


def test_a_misnamed_card_file_is_refused(folder):
    (folder / "cards" / "abc.csv").write_text("code\n", encoding="utf-8")
    m = json.loads((folder / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"].append({"path": "cards/abc.csv", "kind": "card"})
    (folder / gate.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert any("must be named cards/<3 to 6 digits>.csv" in v for v in violations(folder))


def test_the_split_list_must_be_sorted_unique_digits(folder):
    p = folder / gate.CARD_INDEX_PATH
    p.write_text(json.dumps({"version": 1, "splits": ["890", "406"]}), encoding="utf-8")
    assert any("splits" in v for v in violations(folder))
    p.write_text(json.dumps({"version": 1, "splits": ["8x0"]}), encoding="utf-8")
    assert any("splits" in v for v in violations(folder))


def test_a_split_prefix_that_also_has_its_own_file_is_refused(folder):
    splits = json.loads((folder / gate.CARD_INDEX_PATH).read_text(encoding="utf-8"))["splits"]
    assert splits
    s = splits[0]
    (folder / "cards" / f"{s}.csv").write_text("x", encoding="utf-8")
    m = json.loads((folder / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"].append({"path": f"cards/{s}.csv", "kind": "card"})
    (folder / gate.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert any("split list" in v for v in violations(folder))


def test_a_card_file_without_the_index_is_refused(folder):
    m = json.loads((folder / gate.MANIFEST_NAME).read_text(encoding="utf-8"))
    m["files"] = [f for f in m["files"] if f["kind"] != "card_index"]
    (folder / gate.MANIFEST_NAME).write_text(json.dumps(m), encoding="utf-8")
    assert any("card_index" in v for v in violations(folder))


def test_a_card_file_cannot_smuggle_an_email(folder):
    name = "cards/" + a_card_file(folder)
    rewrite(folder, name, lambda t: t.replace("none_flagged", "a@b.example", 1) if "none_flagged" in t else t.replace("one_flagged", "a@b.example", 1))
    assert any("email" in v.lower() or "pattern" in v for v in violations(folder))


def test_the_release_without_cards_still_builds_and_passes(tmp_path):
    ex.build_release(tmp_path, copy.deepcopy(DATASETS), STATUS, SPEC)
    assert not (tmp_path / "cards").exists()
    assert gate.check_release(tmp_path) == []
