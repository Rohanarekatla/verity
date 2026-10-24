"""
B10.3′ — the spend ledger: every call's cost, and the hard cap.

Plan v2, rule 3: *budget is a gate, not a hope.* The runner (A12.1′) owns the
run; this is the piece it enforces the cap with. Every provider given a ledger:

1. asks `ensure_budget(projected)` BEFORE each call, with that call's worst
   case (whole prompt at its dearest rate, every output token used) — so the
   cap is never crossed, rather than noticed one call too late;
2. `record()`s the real cost after it.

With a `path`, entries are appended as JSON lines and re-read on start, so a
resumed run (A12.1′ is resumable) keeps counting from where it stopped
instead of granting itself a fresh budget.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from eval.agentbench.providers.base import Completion, ProviderError


class BudgetExceeded(ProviderError):
    """Refused: this call could take spend past the cap."""

    def __init__(self, spent: float, projected: float, cap: float):
        super().__init__("ledger", f"budget cap ${cap:.2f} reached: spent ${spent:.4f}, "
                                   f"this call could cost up to ${projected:.4f}")
        self.spent, self.projected, self.cap = spent, projected, cap


class CostLedger:
    def __init__(self, cap_usd: Optional[float] = None, path: Optional[Path] = None):
        if cap_usd is not None and cap_usd < 0:
            raise ValueError("cap_usd must be >= 0")
        self.cap_usd = cap_usd
        self.path = Path(path) if path else None
        self.entries: list[dict] = []
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.entries.append(json.loads(line))

    @property
    def total_usd(self) -> float:
        return sum(e["cost_usd"] or 0.0 for e in self.entries)

    def ensure_budget(self, projected_usd: float = 0.0) -> None:
        if self.cap_usd is None:
            return
        if self.total_usd + max(0.0, projected_usd) > self.cap_usd:
            raise BudgetExceeded(self.total_usd, projected_usd, self.cap_usd)

    def record(self, completion: Completion, *, tag: Optional[str] = None) -> dict:
        if completion.cost_usd is None and self.cap_usd is not None:
            # An uncosted call under a cap would make the cap meaningless.
            raise ProviderError("ledger", f"{completion.provider}:{completion.model} has no price; "
                                          "it cannot be run under a spending cap")
        u = completion.usage
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tag": tag,
            "provider": completion.provider,
            "model": completion.model,
            "input_tokens": u.input_tokens,
            "output_tokens": u.output_tokens,
            "cache_read_tokens": u.cache_read_tokens,
            "cache_write_tokens": u.cache_write_tokens,
            "cost_usd": completion.cost_usd,
            "wall_s": completion.timing.wall_s,
            "load_s": completion.timing.load_s,
            "attempts": completion.attempts,
        }
        self.entries.append(entry)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        return entry

    def summary(self) -> dict[str, dict]:
        """Per provider:model — calls, tokens, cache hit share, cost."""
        out: dict[str, dict] = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                                     "cache_read_tokens": 0, "cache_write_tokens": 0,
                                                     "cost_usd": 0.0})
        for e in self.entries:
            s = out[f"{e['provider']}:{e['model']}"]
            s["calls"] += 1
            for k in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"):
                s[k] += e[k]
            s["cost_usd"] += e["cost_usd"] or 0.0
        for s in out.values():
            prompt = s["input_tokens"] + s["cache_read_tokens"] + s["cache_write_tokens"]
            s["cache_read_share"] = (s["cache_read_tokens"] / prompt) if prompt else 0.0
        return dict(out)
