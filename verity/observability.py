"""
B13.3 — `verity-trace.json`, graceful degradation, and the coverage section
(Track B, Week 13; kept from the original B13.1–B13.4).

**A tool that quietly checks less than it claims is worse than one that checks
nothing.** Every stage of `scan_url` already falls back gracefully — a worker
without `traverseTabOrder`, a `sampleRegion` that times out, a contract run
that cannot inventory widgets — and none of those may produce a finding. But
"no findings" from a stage that did not run reads exactly like "no defects"
from a stage that did. This module makes the difference visible:

- `ScanTrace` records each stage's status (`ran` / `degraded` / `skipped`),
  its timing, what it saw, and *why* it degraded;
- `coverage_lines()` turns that into the report's coverage section — what was
  checked, what was not, and why — printed by `verity scan` under every report;
- `to_json()` is `verity-trace.json` (`verity scan --trace PATH`): per-stage
  timing, counts, cache hit rate (multi-page runs), and the model fields
  (load, tokens/sec, escape rate) reported as *not applicable* with the reason,
  never as zero.

The trace travels through a `ContextVar`, so stage helpers deep in the
orchestrator can report degradation without every signature changing; with no
trace active, every call is a no-op.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

Status = Literal["ran", "degraded", "skipped"]

# What each stage checks, in report language — used by the coverage section.
STAGE_CHECKS = {
    "render": "page render (Chromium)",
    "axe": "axe-core rules (WCAG-tagged only)",
    "contrast": "contrast over images/gradients from real pixels (SC 1.4.3)",
    "keyboard": "keyboard: tab order, traps, focus order, focus visible (SC 2.1.1, 2.1.2, 2.4.3, 2.4.7)",
    "contracts": "APG widget contracts: tabs, disclosure, menu button, dialog, combobox (SC 2.1.1, 4.1.2)",
    "vision": "model-assisted judgments (alt-text meaning, text in images)",
}


@dataclass
class StageRecord:
    name: str
    status: Status = "ran"
    seconds: float = 0.0
    reason: Optional[str] = None
    counts: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanTrace:
    target: Optional[str] = None
    stages: dict[str, StageRecord] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # Paths the worker produced for this page (ax-tree.json, dom.html…), for
    # consumers that need more than findings (readiness, the virtual SR).
    artifacts: dict[str, str] = field(default_factory=dict)
    cache_hits: Optional[int] = None
    cache_lookups: Optional[int] = None
    started: float = field(default_factory=time.perf_counter)
    total_seconds: Optional[float] = None

    def stage(self, name: str) -> StageRecord:
        if name not in self.stages:
            self.stages[name] = StageRecord(name)
        return self.stages[name]

    def degrade(self, name: str, reason: str) -> None:
        """A stage that could not (fully) run. Never downgraded back to `ran`."""
        s = self.stage(name)
        if s.status != "skipped":
            s.status = "degraded"
        s.reason = reason if not s.reason else f"{s.reason}; {reason}"

    def skip(self, name: str, reason: str) -> None:
        s = self.stage(name)
        s.status, s.reason = "skipped", reason

    def count(self, name: str, key: str, n: int = 1) -> None:
        c = self.stage(name).counts
        c[key] = c.get(key, 0) + n

    def set(self, name: str, **values: Any) -> None:
        self.stage(name).counts.update(values)

    def finish(self) -> "ScanTrace":
        self.total_seconds = time.perf_counter() - self.started
        return self

    # -- outputs ------------------------------------------------------------------

    def to_json(self) -> dict:
        lookups = self.cache_lookups or 0
        return {
            "schema": "verity-trace/1",
            "target": self.target,
            "total_seconds": self.total_seconds,
            "stages": {
                n: {"status": s.status, "seconds": round(s.seconds, 4), "reason": s.reason, "counts": s.counts}
                for n, s in self.stages.items()
            },
            "cache": {"hits": self.cache_hits, "lookups": self.cache_lookups,
                      "hit_rate": (self.cache_hits or 0) / lookups if lookups else None},
            "model": {
                "load_seconds": None, "tokens_per_second": None, "escape_rate": None,
                "why_null": "no model runs in the scan pipeline (vision is descoped behind a flag, ADR-0002)",
            },
            "not_checked": [line for line in coverage_lines(self) if line.startswith("NOT CHECKED")
                            or line.startswith("PARTIAL")],
            "notes": self.notes,
            "artifacts": self.artifacts,
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), indent=2, default=str), encoding="utf-8")
        return path


_CURRENT: ContextVar[Optional[ScanTrace]] = ContextVar("verity_scan_trace", default=None)


def current() -> Optional[ScanTrace]:
    return _CURRENT.get()


@contextmanager
def activate(trace: Optional[ScanTrace]):
    token = _CURRENT.set(trace)
    try:
        yield trace
    finally:
        _CURRENT.reset(token)


@contextmanager
def timed(name: str):
    """Time a stage on the active trace (no-op without one)."""
    t = current()
    start = time.perf_counter()
    try:
        yield
    finally:
        if t is not None:
            t.stage(name).seconds += time.perf_counter() - start


def degrade(name: str, reason: str) -> None:
    t = current()
    if t is not None:
        t.degrade(name, reason)


def count(name: str, key: str, n: int = 1) -> None:
    t = current()
    if t is not None:
        t.count(name, key, n)


def artifact(key: str, value: Optional[str]) -> None:
    t = current()
    if t is not None and value:
        t.artifacts[key] = str(value)


def note(name: str, **values: Any) -> None:
    t = current()
    if t is not None:
        t.set(name, **values)


# --- the coverage section --------------------------------------------------------------

def coverage_lines(trace: ScanTrace) -> list[str]:
    """
    Exactly what was and was not checked, and why. Every stage in
    STAGE_CHECKS appears — one that never reported is "NOT CHECKED (did not
    run)", never omitted.
    """
    lines: list[str] = []
    for name, what in STAGE_CHECKS.items():
        s = trace.stages.get(name)
        if s is None:
            if name == "vision":
                lines.append(f"NOT CHECKED  {what} — disabled: vision is an experiment behind a flag (ADR-0002); "
                             "these criteria need human review")
            else:
                lines.append(f"NOT CHECKED  {what} — the stage did not run")
            continue
        detail = ", ".join(f"{k}={v}" for k, v in s.counts.items())
        if s.status == "ran" and not _partial(name, s):
            lines.append(f"CHECKED      {what}" + (f" ({detail})" if detail else ""))
        elif s.status == "skipped":
            lines.append(f"NOT CHECKED  {what} — {s.reason}")
        else:
            why = s.reason or _partial_reason(name, s)
            lines.append(f"PARTIAL      {what} — {why}" + (f" ({detail})" if detail else ""))
    return lines


def _partial(name: str, s: StageRecord) -> bool:
    return bool(_partial_reason(name, s))


def _partial_reason(name: str, s: StageRecord) -> str:
    c = s.counts
    bits = []
    if name == "contrast" and c.get("left_for_review"):
        bits.append(f"{c['left_for_review']} region(s) could not be measured and are left for review")
    if name in ("keyboard", "contracts"):
        if c.get("shadow_roots_skipped"):
            bits.append(f"{c['shadow_roots_skipped']} shadow root(s) not entered")
        if c.get("iframes_skipped"):
            bits.append(f"{c['iframes_skipped']} iframe(s) not entered")
        if c.get("unreached"):
            bits.append(f"{c['unreached']} region(s) unreached")
        if c.get("widgets_skipped"):
            bits.append(f"{c['widgets_skipped']} widget(s) beyond the budget not exercised")
        if c.get("incomplete"):
            bits.append("traversal did not complete")
    return "; ".join(bits)


def render_coverage(trace: ScanTrace) -> str:
    return "\n".join(["", " COVERAGE — what this scan did and did not check:", *(f"  {l}" for l in
                                                                                    coverage_lines(trace)), ""])
