"""narrow_handles must change nothing about what the exit function does, only how long it takes."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "p2_lakehouse"))
sys.path.insert(0, str(ROOT / "p4_modelling"))

from gold_lib import fixture  # noqa: E402
from silver_lib import contract, egress  # noqa: E402

C = contract.load()


def rows():
    # placeholder contributor names, as in the silver tests; the second row carries the same name inside a tag list
    return [
        {"code": "9000000000001", "last_modified_t": 1, "product_name": "Cake by user_00077", "brands": "Some Brand", "labels_tags": ["en:organic"]},
        {"code": "9000000000002", "last_modified_t": 2, "product_name": "Bread", "brands": "Other Brand", "labels_tags": ["en:user_00077", "en:vegan"]},
    ]


def test_narrowing_keeps_names_present_and_drops_absent_ones():
    handles = {"user_00077", "user_99999", "absentname1"}
    assert fixture.narrow_handles(rows(), C, handles) == {"user_00077"}


def test_narrowing_matches_case_and_accents_like_the_exit_function_does():
    r = rows()
    r[0]["product_name"] = "Cake by USER_00077"
    assert fixture.narrow_handles(r, C, {"user_00077"}) == {"user_00077"}


def test_exit_result_is_identical_with_the_full_and_the_narrowed_list():
    many = {f"user_{i:05d}" for i in range(2000)} | {"user_00077"}
    full, full_report = egress.prepare_for_export(rows(), C, many)
    narrow, narrow_report = egress.prepare_for_export(rows(), C, fixture.narrow_handles(rows(), C, many))
    assert full == narrow
    assert full_report["names_replaced"] == narrow_report["names_replaced"] >= 2


def test_nothing_to_narrow_gives_an_empty_set():
    assert fixture.narrow_handles(rows(), C, set()) == set()
