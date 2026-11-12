import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bootstrap"))
import run_round2_readers as r  # noqa: E402

UTC = dt.timezone.utc
TABLE = "Nutrition facts per 100 g Energy 376 kJ / 90 kcal Fat 0.5 g Saturates 0.3 g Carbohydrate 8.9 g Sugars 6.5 g Protein 12.4 g Salt 0.06 g"


def test_the_gemini_day_starts_at_0800_utc_which_is_1330_in_india():
    assert r.gemini_day_start(dt.datetime(2026, 11, 10, 17, 9, tzinfo=UTC)) == dt.datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    assert r.gemini_day_start(dt.datetime(2026, 11, 11, 7, 59, tzinfo=UTC)) == dt.datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    assert r.gemini_day_start(dt.datetime(2026, 11, 11, 8, 0, tzinfo=UTC)) == dt.datetime(2026, 11, 11, 8, 0, tzinfo=UTC)


def test_only_calls_since_the_last_reset_are_counted():
    now = dt.datetime(2026, 11, 10, 18, 0, tzinfo=UTC)
    lines = [json.dumps({"at": a}) for a in ("2026-11-10T07:59:00+00:00", "2026-11-10T08:00:00+00:00", "2026-11-10T17:00:00+00:00")] + [""]
    assert r.calls_since_reset(lines, now) == 2


def test_the_plan_sends_nothing_without_a_scan_or_a_table_and_counts_photo_calls_apart():
    rows = [{"code": c} for c in ("a", "b", "c", "d")]
    texts = {"a": TABLE, "b": TABLE, "c": "no table", "d": TABLE}
    p = r.plan(rows, texts.get, lambda c: c == "a", lambda c: c != "d")
    assert p == {"products": 4, "scan_missing": 1, "no_table": 1, "text_calls": 2, "no_photo": 1, "photo_calls": 1}
