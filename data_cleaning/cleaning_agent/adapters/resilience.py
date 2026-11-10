"""Minimal circuit breaker for external calls (org policy: timeout + retry + breaker).

Retries live in the client (Azure SDK retry policy); the breaker sits on top so a
service that keeps failing after those retries is not hammered file after file.
"""

import time
from collections.abc import Callable


class CircuitOpenError(RuntimeError):
    """Raised instead of calling the service while the circuit is open."""


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        reset_after_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or reset_after_s <= 0:
            raise ValueError("failure_threshold >= 1 and reset_after_s > 0")
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if self._clock() - self._opened_at >= self.reset_after_s:
            # Half-open: let the next call through; one failure re-opens it
            self._opened_at = None
            self._failures = self.failure_threshold - 1
            return False
        return True

    def call[T](self, fn: Callable[[], T]) -> T:
        if self.is_open:
            raise CircuitOpenError(f"{self.name}: circuit open after repeated failures")
        try:
            result = fn()
        except Exception:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = self._clock()
            raise
        self._failures = 0
        return result
