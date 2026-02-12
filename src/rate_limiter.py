from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        per_second: int,
        per_hour: int,
        per_day: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.per_second = per_second
        self.per_hour = per_hour
        self.per_day = per_day
        self._now = now_fn or time.time
        self._per_second_hits: dict[str, deque[float]] = defaultdict(deque)
        self._per_hour_hits: dict[str, deque[float]] = defaultdict(deque)
        self._per_day_hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = self._now()
        sec_hits = self._per_second_hits[key]
        hour_hits = self._per_hour_hits[key]
        day_hits = self._per_day_hits[key]

        self._prune(sec_hits, now, 1.0)
        self._prune(hour_hits, now, 3600.0)
        self._prune(day_hits, now, 86400.0)

        if len(sec_hits) >= self.per_second:
            return False
        if len(hour_hits) >= self.per_hour:
            return False
        if len(day_hits) >= self.per_day:
            return False

        sec_hits.append(now)
        hour_hits.append(now)
        day_hits.append(now)
        return True

    @staticmethod
    def _prune(hits: deque[float], now: float, window_seconds: float) -> None:
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
