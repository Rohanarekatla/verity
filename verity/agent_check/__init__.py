"""
A14.1′ — `verity agent-check`: does an AI agent complete a task on this site?

An LLM agent attempts a task through the accessibility tree + keyboard (the same
tree agent the benchmark uses). When it fails, the failure is localised to a
step and a control, pinned to a WCAG criterion, and — the Week-14 safety rule —
only reported as a *confirmed* site defect if Verity's deterministic checks
(B14.1′) agree. Otherwise it is `needs-review`: an unconfirmed agent failure is
never a site defect.
"""

from verity.agent_check.check import (
    AgentCheckResult,
    Localization,
    agent_check,
    default_confirm,
    localize_failure,
)

__all__ = [
    "AgentCheckResult",
    "Localization",
    "agent_check",
    "default_confirm",
    "localize_failure",
]
