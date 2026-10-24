"""The story engine's event finder (item 15), checked on the real daily aggregates of 2026-10-01 to 2026-10-23 (counts only, p8_steward/tests/fixtures)."""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import story_lib as sl  # noqa: E402

FIX = HERE / "fixtures"
DAYS = sl.load_days(FIX / "signal_days.csv")


def test_the_real_data_has_23_complete_days_in_two_scopes_and_an_india_share():
    assert set(DAYS) == {"all", "india"}
    assert len(DAYS["all"]) == len(DAYS["india"]) == 23
    assert abs(DAYS["all"]["2026-10-17"]["india_share"] - 271 / 1802) < 1e-9


def test_the_india_burst_is_found_on_its_first_day():
    events = sl.find_events(DAYS)
    assert sl.first_day(events, "india", ("any_products", "nutrition_products")) == "2026-10-17"
    first = [e for e in events if e.day == "2026-10-17" and e.scope == "india" and e.signal == "any_products"][0]
    assert first.direction == "up" and first.value == 271 and first.baseline == 22


def test_no_event_before_the_history_is_long_enough():
    assert [e for e in sl.find_events(DAYS) if e.day < "2026-10-06"] == []


def test_a_planted_change_turns_the_detector_red_and_removing_it_turns_it_green():
    flat = copy.deepcopy(DAYS)
    for day in [d for d in flat["india"] if d >= "2026-10-17"]:          # the real burst flattened to the usual level of the day before it
        flat["india"][day] = dict(flat["india"]["2026-10-16"])
        flat["all"][day]["india_share"] = flat["india"][day]["any_products"] / flat["all"][day]["any_products"]
    assert [e for e in sl.find_events(flat) if e.scope == "india"] == []
    assert [e for e in sl.find_events(DAYS) if e.scope == "india"]


def test_a_file_name_gives_the_day_its_window_ends():
    assert sl.file_window_end("openfoodfacts_products_1792045568_1792132384.json.gz") == "2026-10-16"
    assert sl.file_window_end("1053923856838696") is None


def test_the_drift_monitors_known_events_are_dated_by_their_files():
    events = sl.drift_events(FIX / "drift_events.csv")
    assert {e["day"] for e in events} == {"2026-10-06", "2026-10-16"}
    assert [e["check"] for e in events if e["day"] == "2026-10-16"] == ["failure_rate"]
    assert sum(1 for e in events if e["day"] == "2026-10-06") == 8
