"""
A17.3 — the crawl budget.

A 25-page audit has to fit a CI budget, which means it must *stop cleanly* when a
limit is reached — not overrun and get killed by the runner, leaving a
half-written report. The budget is a gate checked before each page: pages, wall
time, and (optionally) spend. When one is hit the crawl stops and the report
says so, exactly like the benchmark's ledger stops a run rather than overspend.

The clock is injectable, so the time limit is tested deterministically.
"""

from __future__ import annotations

import time
from typing import Callable, Optional


class BudgetExceeded(Exception):
    """A limit was reached before the next page. Carries which one."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class CrawlBudget:
    def __init__(
        self,
        max_pages: int = 25,
        max_seconds: Optional[float] = None,
        max_usd: Optional[float] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_pages = max_pages
        self.max_seconds = max_seconds
        self.max_usd = max_usd
        self._clock = clock
        self._start: Optional[float] = None
        self.pages = 0
        self.spend = 0.0

    def start(self) -> None:
        self._start = self._clock()

    @property
    def elapsed(self) -> float:
        return 0.0 if self._start is None else max(0.0, self._clock() - self._start)

    def ensure(self) -> None:
        """Call before scanning the next page; raises BudgetExceeded if a limit
        is already reached."""
        if self.pages >= self.max_pages:
            raise BudgetExceeded(f"page budget reached ({self.max_pages})")
        if self.max_seconds is not None and self.elapsed >= self.max_seconds:
            raise BudgetExceeded(f"time budget reached ({self.max_seconds:g}s)")
        if self.max_usd is not None and self.spend >= self.max_usd:
            raise BudgetExceeded(f"spend budget reached (${self.max_usd:.2f})")

    def record(self, *, usd: float = 0.0) -> None:
        """Account one scanned page."""
        self.pages += 1
        self.spend += usd

    @property
    def remaining_pages(self) -> int:
        return max(0, self.max_pages - self.pages)
