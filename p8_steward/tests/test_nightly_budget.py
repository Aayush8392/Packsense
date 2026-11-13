"""Tests for the nightly call budget (nightly/budget.py): the ceiling, the pacing, the 503 streak and the time limit."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nightly import budget as b  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def make(**kw):
    c = Clock()
    return b.Budget(clock=c.now, sleep=c.sleep, **kw), c


def test_the_ceiling_is_hard_and_the_request_that_would_pass_it_is_refused():
    bud, _ = make(max_calls=3)
    for _ in range(3):
        bud.spend()
    assert bud.calls == 3 and bud.remaining() == 0
    with pytest.raises(b.Stop) as e:
        bud.spend()
    assert e.value.reason == "call_ceiling" and bud.calls == 3


def test_requests_are_paced_to_the_per_minute_limit():
    bud, c = make(per_minute=15)
    bud.spend()
    bud.spend()
    assert c.slept == [4.0] and bud.calls == 2
    c.t += 10                                  # a slow step already used the gap: no wait
    bud.spend()
    assert c.slept == [4.0]


def test_a_run_of_transient_errors_ends_the_night_and_a_success_resets_the_run():
    bud, _ = make(max_503_streak=3)
    bud.unavailable()
    bud.unavailable()
    bud.ok()
    bud.unavailable()
    bud.unavailable()
    with pytest.raises(b.Stop) as e:
        bud.unavailable()
    assert e.value.reason == "503_streak"


def test_the_time_limit_stops_before_the_next_request():
    bud, c = make(max_seconds=100)
    bud.spend()
    c.t += 101
    with pytest.raises(b.Stop) as e:
        bud.spend()
    assert e.value.reason == "time_limit" and bud.calls == 1


def test_the_defaults_are_the_agreed_ceiling_and_the_free_tier_pace():
    assert b.MAX_CALLS == 400 and b.PER_MINUTE == 15
