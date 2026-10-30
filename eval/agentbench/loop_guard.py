"""
A13.3 — state labelling and the loop guard.

An agent that cannot make progress does not fail cleanly; it thrashes —
re-reading the same page and re-issuing the same action until the step cap runs
out, burning tokens and budget. Under a defect that is exactly the common
failure (the control it needs has no name, so every attempt is identical), so
catching the loop early is both a cost control and a cleaner signal: "stuck in a
loop on this state" is a more honest episode end than "ran out of steps".

Two cheap, deterministic signals, no model:

- **State labelling** — a stable label for a page state, from its observation
  (the AXTree or DOM the agent saw), normalised so cosmetic whitespace does not
  make two identical states look different.
- **The loop guard** — trips when the *same (state, action)* pair repeats
  `max_repeats` times (the agent is banging on the same control) or a single
  state is visited `max_state_visits` times (thrashing between a few states
  without progress).

A tripped guard ends the episode as a **task failure**, never an error: the
agent genuinely failed to make progress, which under a defect is the effect
being measured — not an infrastructure problem to exclude.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field


def state_label(observation: str) -> str:
    """A stable 12-hex label for a page state. Whitespace-normalised so two
    renders of the same state collide (and a genuinely different state does
    not)."""
    norm = "\n".join(line.rstrip() for line in (observation or "").strip().splitlines())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


@dataclass
class LoopGuard:
    """Tracks (state, action) and state visit counts for one episode."""

    max_repeats: int = 3          # same (state, action) this many times -> loop
    max_state_visits: int = 8     # one state visited this many times -> thrash
    _pairs: Counter = field(default_factory=Counter)
    _states: Counter = field(default_factory=Counter)
    tripped_on: str = ""

    def record(self, state: str, action: str) -> bool:
        """Record one step; return True when a loop is detected."""
        self._pairs[(state, action)] += 1
        self._states[state] += 1
        if self._pairs[(state, action)] >= self.max_repeats:
            self.tripped_on = f"repeated action {action!r} on the same state {self._pairs[(state, action)]}x"
            return True
        if self._states[state] >= self.max_state_visits:
            self.tripped_on = f"state revisited {self._states[state]}x without progress"
            return True
        return False

    def reset(self) -> None:
        self._pairs.clear()
        self._states.clear()
        self.tripped_on = ""
