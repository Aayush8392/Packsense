"""The call budget of the nightly job: a hard ceiling counted per request, pacing, a stop after a run of 503s, and a wall-clock limit (A121 settled 2026-11-13).

Every model request is counted BEFORE it is made, so a failed request costs budget exactly as it costs quota. `Stop` ends the whole night with a named reason; nothing here
retries. The defaults are provisional: the ceiling (400 of the free tier's 500 a day) and pacing (15 a minute) come from the free-tier limits; the 503 streak and the time limit are to be
set from the soak test's measured times, not guessed.
"""
from __future__ import annotations

import time

MAX_CALLS = 400            # of 500 a day on the free tier; the rest is headroom for a manual test on the same key
PER_MINUTE = 15            # the free tier's per-minute limit
MAX_503_STREAK = 4         # provisional
MAX_SECONDS = 3 * 3600     # provisional; GitHub Actions allows 6 hours


class Stop(Exception):
    """The night ends here; `reason` is one of call_ceiling, time_limit, 503_streak, model_mismatch, freeze_broken, canary_failed."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class TransientError(Exception):
    """A request failed in a way that may pass (503 'high demand', a timeout, a rate limit)."""


class Budget:
    def __init__(self, max_calls: int = MAX_CALLS, per_minute: int = PER_MINUTE, max_503_streak: int = MAX_503_STREAK, max_seconds: float = MAX_SECONDS,
                 clock=time.monotonic, sleep=time.sleep):
        self.max_calls, self.max_503_streak, self.max_seconds = max_calls, max_503_streak, max_seconds
        self.gap = 60.0 / per_minute
        self.clock, self.sleep = clock, sleep
        self.calls = 0
        self.streak = 0
        self.started = clock()
        self._last: float | None = None

    def remaining(self) -> int:
        return self.max_calls - self.calls

    def check_time(self) -> None:
        if self.clock() - self.started >= self.max_seconds:
            raise Stop("time_limit")

    def spend(self) -> None:
        """Count one request and wait out the pacing gap; raises Stop when the ceiling or the time limit is reached."""
        if self.calls >= self.max_calls:
            raise Stop("call_ceiling")
        self.check_time()
        if self._last is not None:
            wait = self.gap - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.clock()
        self.calls += 1

    def ok(self) -> None:
        self.streak = 0

    def unavailable(self) -> None:
        """A request failed with a transient error; a run of them ends the night."""
        self.streak += 1
        if self.streak >= self.max_503_streak:
            raise Stop("503_streak")
