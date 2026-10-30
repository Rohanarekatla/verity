"""
A14.1′ — the agent-check core: run, localise, confirm.

Three steps, each a seam so the whole flow is tested without a browser or a
model:

1. **Run.** The tree agent attempts the task against the page (a `WebEnv`). The
   agent is unchanged from the benchmark — that is the point.

2. **Localise.** If the agent did not succeed, pin the failure to a step and a
   control. "The agent gave up" becomes "step 7, the control it needed has no
   accessible name (4.1.2)". We read the agent's own trace — the accessibility
   tree it saw at the stuck step — and find the first nameable control with no
   name, or a roleless clickable, using the same AXTree parser the injection
   verifier uses. No model, no guess: if nothing localisable is there, we say
   so and the finding is generic.

3. **Confirm.** The Week-14 safety rule (ADR, gate §): *an unconfirmed agent
   failure is never reported as a site defect.* The default confirmer therefore
   returns `needs-review` for every localisation — confirmations are OFF until
   Track B's deterministic confirmation (B14.1′) is wired in and measured at
   zero wrong confirmations. A caller passes a real `confirm_fn` to upgrade a
   localisation to a confirmed, authoritative finding.

Success itself is never judged by a model: with a `--success` spec the
deterministic evaluators decide; without one, the agent's own
`done`/`report_infeasible`/loop verdict stands, and the report says it was
self-reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from eval.agentbench.verify_injection import parse_tree
from verity.models.schemas import (
    Confidence,
    Evidence,
    Finding,
    Level,
    Modality,
    Provenance,
)

# WCAG criteria agent-check pins failures to. Agent task failures are
# overwhelmingly name/role (the agent cannot address a control) or keyboard, so
# these two cover the localised cases; everything else is a generic 4.1.2.
_SC = {
    "4.1.2": ("Name, Role, Value", Level.A),
    "2.1.1": ("Keyboard", Level.A),
}


@dataclass
class Localization:
    """Where an agent failure was pinned."""

    step: int
    sc_id: str
    reason: str
    selector: Optional[str] = None
    ax_node_id: Optional[str] = None
    observation: str = ""


@dataclass
class AgentCheckResult:
    url: str
    task: str
    succeeded: bool
    verdict: str                       # passed | failed | infeasible | looped
    findings: list = field(default_factory=list)
    localization: Optional[Localization] = None
    success_source: str = "self-reported"   # or "deterministic (--success)"
    episode: object = None             # the raw Episode, for the trace report


# -- confirmation seam (B14.1′) ----------------------------------------------

# A confirmer takes a Localization and returns (provenance, confidence, outcome).
ConfirmFn = Callable[[Localization], tuple]


def default_confirm(loc: Localization) -> tuple:
    """
    The safe default: do NOT confirm. Every localisation is `needs-review`, so
    agent-check never claims a site defect it has not deterministically proven.
    This is the Week-14 fallback ("confirmations disabled until zero wrong
    confirmations"); B14.1′ replaces it with the real checks.
    """
    return (Provenance.NEEDS_REVIEW,
            Confidence(score=0.0, method="agent-check-unconfirmed", model=None, escape_used=True),
            "cantTell")


# -- localisation -------------------------------------------------------------

def localize_failure(episode, result) -> Optional[Localization]:
    """
    Pin a failed episode to a step and a control. Returns None if the episode
    succeeded. Deterministic: reads the trace the agent produced.
    """
    steps = episode.steps
    if not steps:
        return Localization(step=0, sc_id="4.1.2",
                            reason="the agent took no action; the page exposed no control it could use")

    # The stuck step: where it reported infeasible, where the loop guard fired,
    # else the last step (cap reached or a failed final action).
    idx = len(steps) - 1
    for i, s in enumerate(steps):
        if s.action in ("report_infeasible",) or (s.action or "").startswith("<loop-guard"):
            idx = i
            break
    step = steps[idx]
    obs = step.observation or ""

    # Find the control the agent could not use: a nameable control with no name,
    # or a roleless clickable — the realistic reason a task is unreachable.
    for node in parse_tree(obs):
        nameable = node.role in {"button", "link", "textbox", "checkbox", "radio",
                                 "combobox", "menuitem", "searchbox", "switch"}
        if nameable and not node.name.strip():
            return Localization(
                step=idx + 1, sc_id="4.1.2",
                reason=f"a {node.role} the task needs has no accessible name",
                selector=f'[data-vbid="{node.bid}"]' if node.bid else None,
                ax_node_id=node.bid, observation=obs,
            )
        if node.role in ("generic", "") and node.clickable:
            return Localization(
                step=idx + 1, sc_id="4.1.2",
                reason="the agent faced a clickable element with no role and no name (a div-button)",
                selector=f'[data-vbid="{node.bid}"]' if node.bid else None,
                ax_node_id=node.bid, observation=obs,
            )

    return Localization(
        step=idx + 1, sc_id="4.1.2",
        reason="the agent could not complete the task from the accessibility tree available",
        observation=obs,
    )


# -- finding construction -----------------------------------------------------

def _finding_from_localization(url: str, task: str, loc: Localization, confirm_fn: ConfirmFn,
                               page_state_hash: str) -> Finding:
    from verity.orchestrator.main import derive_finding_id

    provenance, confidence, outcome = confirm_fn(loc)
    sc_name, level = _SC.get(loc.sc_id, ("Name, Role, Value", Level.A))
    rule_id = f"agent-check/{loc.sc_id}"
    selector = loc.selector or url
    verb = {"fail": "confirmed", "cantTell": "needs review", "pass": "cleared"}.get(outcome, "needs review")
    from verity.models.schemas import SuccessCriterion
    from verity.agents.validator.severity import assign_severity

    return Finding(
        id=derive_finding_id(rule_id, selector),
        rule_id=rule_id,
        sc=SuccessCriterion(id=loc.sc_id, name=sc_name, level=level, modality=Modality.INTERACTION),
        provenance=provenance,
        severity=assign_severity(sc_id=loc.sc_id, level=level, outcome=outcome,
                                 provenance=provenance, engine_impact=None),
        confidence=confidence,
        agent="agent-check",
        engine="agentbench-tree",
        outcome=outcome,
        message=(f"Agent could not complete the task “{task}” — {loc.reason} "
                 f"(step {loc.step}; {verb})."),
        evidence=Evidence(
            dom_selector=loc.selector,
            ax_node_id=loc.ax_node_id,
            computed_values={"stuck_step": loc.step, "task": task,
                             "accessibility_tree": loc.observation[:2000]},
        ),
        page_state_hash=page_state_hash,
    )


# -- the orchestration --------------------------------------------------------

def _verdict(episode, result, succeeded: bool) -> str:
    if succeeded:
        return "passed"
    if getattr(result, "infeasible", False):
        return "infeasible"
    if getattr(result, "looped", False):
        return "looped"
    return "failed"


def agent_check(
    url: str,
    task: str,
    *,
    agent,
    env,
    success_fn: Optional[Callable[[object], str]] = None,
    confirm_fn: ConfirmFn = default_confirm,
    page_state_hash: str = "",
) -> AgentCheckResult:
    """
    Run `agent` against `env` attempting `task`, and return the check result.

    `success_fn(env) -> "success"|"failure"|"indeterminate"` decides success
    deterministically (the `--success` evaluators); without it, success is the
    agent's own verdict. A failed check yields exactly one localised finding,
    `needs-review` unless `confirm_fn` upgrades it.
    """
    result = agent.run(env, task=url, seed=0, defect=None)
    episode = result.episode

    if success_fn is not None:
        outcome = success_fn(env)
        succeeded = outcome == "success"
        source = "deterministic (--success)"
    else:
        succeeded = bool(episode.done) and not getattr(result, "infeasible", False) \
            and not getattr(result, "looped", False)
        source = "self-reported"

    findings: list[Finding] = []
    loc: Optional[Localization] = None
    if not succeeded:
        loc = localize_failure(episode, result)
        findings.append(_finding_from_localization(url, task, loc, confirm_fn, page_state_hash))

    return AgentCheckResult(
        url=url, task=task, succeeded=succeeded, verdict=_verdict(episode, result, succeeded),
        findings=findings, localization=loc, success_source=source, episode=episode,
    )
