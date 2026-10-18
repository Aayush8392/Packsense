"""Secret-expiry check: the date arithmetic and the list validation.

The inputs are generic labels and fixed dates, on purpose: the real list is private (a repository variable) and must not
appear in this public repository. These tests check arithmetic, not data. The end-to-end proof is the workflow itself: a
manual run with a 30-day threshold must go red on the real list, and a normal run must go green.
"""
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from check_secret_expiry import due, parse_list, report_lines  # noqa: E402

TODAY = dt.date(2026, 10, 18)


def entries(*pairs):
    return parse_list(json.dumps([{"name": n, "expires": e} for n, e in pairs]))


def test_exactly_the_threshold_is_due_and_one_day_more_is_not():
    es = entries(("a", "2026-10-28"), ("b", "2026-10-29"))
    assert [h[0] for h in due(es, TODAY, 10)] == ["a"]


def test_an_expired_entry_is_due_with_negative_days():
    hits = due(entries(("a", "2026-10-15")), TODAY, 10)
    assert hits == [("a", -3, dt.date(2026, 10, 15))]
    assert "EXPIRED 3 day(s) ago" in report_lines(hits)[0]


def test_expiring_today_is_due_with_zero_days_left():
    assert due(entries(("a", "2026-10-18")), TODAY, 10)[0][1] == 0


def test_no_expiry_is_never_due_and_results_are_soonest_first():
    es = entries(("never", None), ("later", "2026-10-25"), ("soon", "2026-10-20"))
    assert [h[0] for h in due(es, TODAY, 10)] == ["soon", "later"]


def test_a_bigger_threshold_catches_more():
    es = entries(("a", "2026-11-13"))
    assert due(es, TODAY, 10) == []
    assert [h[0] for h in due(es, TODAY, 30)] == ["a"]


@pytest.mark.parametrize("bad", [
    "", "not json", "{}", "[]",
    '[{"name": "", "expires": "2026-10-18"}]',
    '[{"expires": "2026-10-18"}]',
    '[{"name": "a", "expires": "18/10/2026"}]',
    '[{"name": "a", "expires": 5}]',
    '[{"name": "a", "expires": null}, {"name": "a", "expires": null}]',
])
def test_a_malformed_list_is_refused(bad):
    with pytest.raises(ValueError):
        parse_list(bad)


def test_the_error_message_never_repeats_the_content():
    with pytest.raises(ValueError) as e:
        parse_list('[{"name": "very-secret-label", "expires": "tomorrow"}]')
    assert "very-secret-label" not in str(e.value)
