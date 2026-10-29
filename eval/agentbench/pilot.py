"""
A10.4 pilot harness — the Week-10 pilot.

The pilot's only job (plan, W10 artifact) is to **measure cost and variance** so
Week 12 can be sized: a few tasks × {clean, one name defect, div-button} × a few
trials, across one local and one frontier model. It is deliberately *not* the
full benchmark runner — that is A12.1′, which owns pre-registration, the sample
sizes this pilot computes, and the exclusion rules. This just runs the matrix
and reports tokens/episode, cost/episode, and per-cell success variance.

Success is the env's own reward (MiniWoB computes it from the solved state),
never an LLM judgment — the same rule the deterministic evaluators (B11.1′)
enforce. Budget is a gate: a `CostLedger` with a hard cap refuses a call before
it would overspend, so a runaway model costs a fixed amount, not a surprise.

Everything is injectable (providers, env factory, agent factory) so the
aggregation is tested with a fake provider and a fake env, no browser or
network. A real run needs API keys and is the operator's to start.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Optional

from eval.agentbench.agents.tree_agent import TreeAgent
from eval.agentbench.env import MiniWoBEnv
from eval.agentbench.providers.base import BaseProvider, ProviderError

# The pilot matrix defaults (small, by design — this sizes W12, it is not W12).
PILOT_TASKS = ("click-button", "click-link", "enter-text", "click-checkboxes", "login-user")
# variant name -> defect passed to env.reset (None = the clean control).
PILOT_VARIANTS = {"clean": None, "label-stripped": "stripName", "div-button": "divButton"}
PILOT_TRIALS = 10


@dataclass
class CellStats:
    """One (model × task × variant) cell: the unit the pilot reports."""

    model: str
    task: str
    variant: str
    n: int = 0
    successes: int = 0
    errors: int = 0
    infeasible: int = 0
    tokens: list[int] = field(default_factory=list)
    costs: list[float] = field(default_factory=list)
    steps: list[int] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        scored = self.n - self.errors
        return self.successes / scored if scored else 0.0

    @property
    def tokens_mean(self) -> float:
        return statistics.fmean(self.tokens) if self.tokens else 0.0

    @property
    def tokens_sd(self) -> float:
        return statistics.pstdev(self.tokens) if len(self.tokens) > 1 else 0.0

    @property
    def cost_mean(self) -> float:
        return statistics.fmean(self.costs) if self.costs else 0.0

    @property
    def cost_total(self) -> float:
        return sum(self.costs)

    @property
    def steps_mean(self) -> float:
        return statistics.fmean(self.steps) if self.steps else 0.0


def run_pilot(
    models: dict[str, BaseProvider],
    *,
    tasks: tuple[str, ...] = PILOT_TASKS,
    variants: Optional[dict[str, Optional[str]]] = None,
    trials: int = PILOT_TRIALS,
    max_steps: int = 15,
    headless: bool = True,
    env_factory: Callable[..., "MiniWoBEnv"] = MiniWoBEnv,
    agent_factory: Callable[[BaseProvider], TreeAgent] = lambda p: TreeAgent(p),
) -> list[CellStats]:
    """
    Run the pilot matrix and return per-cell stats.

    `models` maps a label (e.g. "frontier", "local") to a ready provider — the
    caller builds them with `make_provider`, so the budget ledger and pricing
    are already wired. An episode that raises `ProviderError` (including a
    budget stop) is recorded as an *error* and excluded from the success rate,
    never counted as a task failure.
    """
    variants = PILOT_VARIANTS if variants is None else variants
    cells: list[CellStats] = []

    for label, provider in models.items():
        agent = agent_factory(provider)
        with env_factory(headless=headless) as env:
            for task in tasks:
                for vname, defect in variants.items():
                    cell = CellStats(model=label, task=task, variant=vname)
                    for seed in range(trials):
                        cell.n += 1
                        try:
                            r = agent.run(env, task, seed=seed, defect=defect)
                        except ProviderError:
                            cell.errors += 1
                            continue
                        if r.episode.reward > 0:
                            cell.successes += 1
                        if r.infeasible:
                            cell.infeasible += 1
                        cell.tokens.append(r.total_tokens)
                        cell.costs.append(r.cost_usd)
                        cell.steps.append(r.steps_used)
                    cells.append(cell)
    return cells


def format_report(cells: list[CellStats], *, title: str = "AgentBench pilot") -> str:
    """Render the pilot cells as the Markdown the W10 gate records."""
    lines = [f"# {title}", ""]
    total_cost = sum(c.cost_total for c in cells)
    lines.append(f"**Total cost:** ${total_cost:.4f}  ·  **cells:** {len(cells)}")
    lines.append("")
    lines.append("| model | task | variant | n | success | tok μ | tok σ | $/ep | steps μ | infeasible | err |")
    lines.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|--:|")
    for c in cells:
        lines.append(
            f"| {c.model} | {c.task} | {c.variant} | {c.n} | {c.success_rate:.0%} | "
            f"{c.tokens_mean:.0f} | {c.tokens_sd:.0f} | ${c.cost_mean:.4f} | "
            f"{c.steps_mean:.1f} | {c.infeasible} | {c.errors} |"
        )
    lines.append("")
    lines.append(
        "σ (token variance) and the clean-vs-defect success gap are what W12's "
        "sample size is computed from. A null result here (defects don't move "
        "success) is itself a finding — do not tune to force a gap."
    )
    return "\n".join(lines) + "\n"
