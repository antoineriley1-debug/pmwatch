"""Question timer (spec section 8). Starts when a new question is recognized;
paused time is excluded."""
from __future__ import annotations

import time


class QuestionTimer:
    def __init__(self, minimum_seconds: float, maximum_seconds: float):
        self.minimum = minimum_seconds
        self.maximum = maximum_seconds
        self._started: float | None = None
        self._paused_at: float | None = None
        self._paused_total = 0.0

    def start(self) -> None:
        self._started = time.monotonic()
        self._paused_at = None
        self._paused_total = 0.0

    def pause(self) -> None:
        if self._started is not None and self._paused_at is None:
            self._paused_at = time.monotonic()

    def resume(self) -> None:
        if self._paused_at is not None:
            self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None

    @property
    def running(self) -> bool:
        return self._started is not None

    def elapsed(self) -> float:
        if self._started is None:
            return 0.0
        now = self._paused_at if self._paused_at is not None else time.monotonic()
        return now - self._started - self._paused_total

    def minimum_remaining(self) -> float:
        return max(0.0, self.minimum - self.elapsed())

    def minimum_met(self) -> bool:
        return self.elapsed() >= self.minimum

    def maximum_exceeded(self) -> bool:
        return self.elapsed() >= self.maximum

    def stop(self) -> float:
        elapsed = self.elapsed()
        self._started = None
        return elapsed
