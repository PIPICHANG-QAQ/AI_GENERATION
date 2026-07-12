"""Priority-aware adaptive concurrency for standardization provider calls."""

from __future__ import annotations

import heapq
import os
import threading
import time
from contextlib import contextmanager
from itertools import count
from typing import Callable, Iterator


class AdaptiveConcurrencyGate:
    """A condition-based AIMD gate whose limit can change safely at runtime."""

    PRIORITIES = {
        "interactive": 0,
        "retry": 1,
        "batch": 2,
        "automatic": 3,
    }

    def __init__(
        self,
        *,
        initial: int,
        minimum: int,
        maximum: int,
        success_window: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.minimum = max(1, int(minimum))
        self.maximum = max(self.minimum, int(maximum))
        self.limit = min(self.maximum, max(self.minimum, int(initial)))
        self.success_window = max(1, int(success_window))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.clock = clock
        self.active = 0
        self.cooldown_until = 0.0
        self.successes = 0
        self.latencies: list[int] = []
        self.baseline_latency_ms: float | None = None
        self.condition = threading.Condition(threading.RLock())
        self.tickets = count()
        self.waiters: list[tuple[int, int]] = []

    def priority_value(self, priority: str) -> int:
        return self.PRIORITIES.get(str(priority or "batch").strip().lower(), self.PRIORITIES["batch"])

    @contextmanager
    def slot(self, priority: str = "batch") -> Iterator[None]:
        waiter = (self.priority_value(priority), next(self.tickets))
        with self.condition:
            heapq.heappush(self.waiters, waiter)
            while self.active >= self.limit or not self.waiters or self.waiters[0] != waiter:
                self.condition.wait()
            heapq.heappop(self.waiters)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active = max(0, self.active - 1)
                self.condition.notify_all()

    def record_success(self, duration_ms: int) -> None:
        with self.condition:
            if self.clock() < self.cooldown_until:
                return
            self.successes += 1
            self.latencies.append(max(0, int(duration_ms)))
            if self.successes < self.success_window:
                return
            average = sum(self.latencies) / max(1, len(self.latencies))
            latency_stable = self.baseline_latency_ms is None or average <= self.baseline_latency_ms * 1.5
            if self.baseline_latency_ms is None:
                self.baseline_latency_ms = average
            if latency_stable and self.limit < self.maximum:
                self.limit += 1
                self.condition.notify_all()
            self.successes = 0
            self.latencies.clear()

    def record_failure(self, kind: str) -> None:
        if str(kind or "").strip().lower() not in {"rate_limit", "service_unavailable", "timeout"}:
            return
        with self.condition:
            self.limit = max(self.minimum, self.limit // 2)
            self.cooldown_until = self.clock() + self.cooldown_seconds
            self.successes = 0
            self.latencies.clear()
            self.condition.notify_all()

    def snapshot(self) -> dict[str, int | bool]:
        with self.condition:
            return {
                "active": self.active,
                "limit": self.limit,
                "minimum": self.minimum,
                "maximum": self.maximum,
                "cooldown": self.clock() < self.cooldown_until,
            }


_STANDARDIZATION_GATE: AdaptiveConcurrencyGate | None = None
_STANDARDIZATION_GATE_LOCK = threading.RLock()


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return min(maximum, max(minimum, int(os.getenv(name, str(default)))))
    except (TypeError, ValueError):
        return default


def standardization_concurrency_gate() -> AdaptiveConcurrencyGate:
    global _STANDARDIZATION_GATE
    with _STANDARDIZATION_GATE_LOCK:
        if _STANDARDIZATION_GATE is None:
            minimum = _int_env("LLM_STANDARDIZE_MIN_CONCURRENCY", 2, 1, 16)
            maximum = _int_env("LLM_STANDARDIZE_MAX_CONCURRENCY", 8, minimum, 16)
            initial = _int_env("LLM_STANDARDIZE_INITIAL_CONCURRENCY", 4, minimum, maximum)
            _STANDARDIZATION_GATE = AdaptiveConcurrencyGate(
                initial=initial,
                minimum=minimum,
                maximum=maximum,
                success_window=_int_env("LLM_STANDARDIZE_SUCCESS_WINDOW", 20, 1, 1000),
                cooldown_seconds=float(os.getenv("LLM_STANDARDIZE_COOLDOWN_SECONDS", "30")),
            )
        return _STANDARDIZATION_GATE


def reset_standardization_concurrency_gate() -> None:
    global _STANDARDIZATION_GATE
    with _STANDARDIZATION_GATE_LOCK:
        _STANDARDIZATION_GATE = None
