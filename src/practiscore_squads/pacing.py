"""Request pacing & backoff (NF6, implementation.md §3.2).

Keeps a single process from bursting the API: `wait()` sleeps a jittered gap
since the last request so consecutive calls stay near-human, and `penalize()`
sleeps an exponentially growing (capped) delay after a throttle response.
"""
from __future__ import annotations

import random
import time


class Pacer:
    def __init__(self, min_gap: float = 0.8, max_gap: float = 1.6,
                 backoff_base: float = 2.0, backoff_cap: float = 60.0):
        self.min_gap = min_gap
        self.max_gap = max_gap
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self._last: float | None = None

    def wait(self) -> None:
        target = random.uniform(self.min_gap, self.max_gap)
        now = time.monotonic()
        if self._last is not None:
            elapsed = now - self._last
            remaining = target - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._last = time.monotonic()

    def penalize(self, attempt: int) -> None:
        raw = self.backoff_base ** attempt
        jittered = raw + random.uniform(0, raw * 0.1)
        delay = min(self.backoff_cap, jittered)
        time.sleep(delay)

    def reset(self) -> None:
        self._last = None
