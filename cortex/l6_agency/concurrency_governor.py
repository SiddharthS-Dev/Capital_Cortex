"""concurrency_governor (§6 L6): at most N agents in parallel (default 4), a per-task token ceiling, the
run's own token/$ budget, and the daily $ budget (enforced by the LLM router's ledger). When a limit is
hit the run degrades gracefully: agents that can't start are skipped and the run is marked incomplete."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConcurrencyGovernor:
    max_parallel: int = 4
    run_budget_tokens: int | None = None
    run_budget_usd: float | None = None
    tokens_used: int = 0
    usd_used: float = 0.0
    exhausted: str | None = None
    skipped: list[str] = field(default_factory=list)
    _sem: asyncio.Semaphore | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def __post_init__(self) -> None:
        self._sem = asyncio.Semaphore(max(1, self.max_parallel))

    @asynccontextmanager
    async def slot(self) -> Any:
        assert self._sem is not None
        async with self._sem:
            yield

    def remaining_tokens(self, task_ceiling: int) -> int:
        """Tokens this task may still use: the lower of its own ceiling and what's left of the run budget."""
        left = task_ceiling
        if self.run_budget_tokens is not None:
            left = min(left, self.run_budget_tokens - self.tokens_used)
        return max(0, left)

    def can_start(self, estimate_usd: float = 0.0) -> bool:
        if self.exhausted:
            return False
        if self.run_budget_tokens is not None and self.tokens_used >= self.run_budget_tokens:
            self.exhausted = "run token budget reached"
            return False
        if self.run_budget_usd is not None and self.usd_used + estimate_usd > self.run_budget_usd:
            self.exhausted = "run $ budget reached"
            return False
        return True

    async def record(self, tokens: int, usd: float) -> None:
        async with self._lock:
            self.tokens_used += tokens
            self.usd_used += usd

    def mark_exhausted(self, reason: str) -> None:
        self.exhausted = self.exhausted or reason
