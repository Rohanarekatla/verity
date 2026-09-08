"""
verity/agents/keyboard.py — keyboard traversal judgments (B4.1, B4.2, B4.4).

Track A presses Tab and records what happened. This module decides what that
means against WCAG, and — more often than you would expect — decides that it
does not know.

Week 4's gate is **injected trap detected, zero false alarms on clean APG
widgets**. Correctly-built widgets are the hard case, not the broken ones:
a tablist that implements roving tabindex has exactly one tab stop for six
tabs, by design, and a naive checker screams. The plan is explicit that
*every false alarm on a correctly-built widget is a design bug*, so almost
all of the care below is about not crying wolf.

No model is involved anywhere in this file.
"""

import asyncio
import logging
from typing import Awaitable, Callable, Literal, Optional

from verity.models.schemas import (
    Confidence,
    Evidence,
    Finding,
    Level,
    Modality,
    Provenance,
    Severity,
    SuccessCriterion,
    TabStop,
    TraversalResult,
    UnreachedReason,
)

logger = logging.getLogger(__name__)

# B4.2 — the three states, before they become Finding outcomes.
#
# `indeterminate` is not a polite word for "fail". It means the traversal did
# not gather enough evidence to say either way, and it maps to
# outcome=cantTell / provenance=NEEDS_REVIEW, which never gates a build.
Outcome = Literal["pass", "fail", "indeterminate"]


# --- B4.1: the four success criteria this evidence can speak to -------------

_CRITERIA: dict[str, tuple[str, Level]] = {
    "2.1.1": ("Keyboard", Level.A),
    "2.1.2": ("No Keyboard Trap", Level.A),
    "2.4.3": ("Focus Order", Level.A),
    "2.4.7": ("Focus Visible", Level.AA),
}


def _criterion(sc_id: str) -> SuccessCriterion:
    name, level = _CRITERIA[sc_id]
    return SuccessCriterion(
        id=sc_id,
        name=name,
        level=level,
        # Keyboard results come from driving the page, not from reading it.
        modality=Modality.INTERACTION,
    )


def _finding(
    sc_id: str,
    outcome: Outcome,
    message: str,
    *,
    page_state_hash: str,
    selector: Optional[str] = None,
    trace: Optional[list[str]] = None,
    details: Optional[dict] = None,
    severity: Severity = Severity.SERIOUS,
) -> Finding:
    """
    Build one Finding, with provenance and confidence that match the outcome.

    B4.2 lives here: `indeterminate` becomes `cantTell` + `NEEDS_REVIEW` +
    confidence 0.0. A finding may not claim certainty it does not have — the
    same rule the contrast adjudicator follows.
    """
    from verity.orchestrator.main import derive_finding_id

    rule_id = f"keyboard-{sc_id.replace('.', '')}"
    resolved = outcome in ("pass", "fail")

    return Finding(
        id=derive_finding_id(rule_id, selector or ""),
        rule_id=rule_id,
        sc=_criterion(sc_id),
        provenance=Provenance.AUTHORITATIVE if resolved else Provenance.NEEDS_REVIEW,
        severity=severity,
        confidence=Confidence(
            score=1.0 if resolved else 0.0,
            method="keyboard-traversal" if resolved else "keyboard-indeterminate",
            model=None,
            escape_used=False,
        ),
        agent="keyboard",
        engine="node-worker",
        outcome="cantTell" if outcome == "indeterminate" else outcome,
        message=message,
        evidence=Evidence(
            dom_selector=selector,
            interaction_trace=trace,
            computed_values=details or {},
        ),
        page_state_hash=page_state_hash,
    )


# --- the four judgments ----------------------------------------------------

def judge_keyboard_operable(result: TraversalResult, page_state_hash: str) -> Finding:
    """
    **SC 2.1.1 Keyboard** — can everything be operated from the keyboard?

    A focusable element the traversal never reached is the failure signal.
    But `unreached` carries a *reason*, and the three kinds are not the same:

    - `NOT_FOCUSABLE` / `OBSCURED` — a real barrier. The user cannot get there.
    - `SHADOW_DOM` / `IFRAME` / `UNKNOWN` — our traversal's limitation, not the
      page's. Reporting these as failures would blame a site for our own blind
      spot, which is the definition of a false positive.
    - `ARROW_NAVIGABLE` — **not a problem at all.** The roving-tabindex
      pattern (tablist, menu, radiogroup, tree, grid) deliberately exposes one
      Tab stop and moves within the widget using arrow keys. A tablist with
      six tabs correctly shows five elements Tab never lands on. Pressing only
      Tab does not prove they are unreachable; it proves we did not press the
      right key. See `data/apg-contracts/tablist.yaml`.
    """
    if not result.complete:
        return _finding(
            "2.1.1", "indeterminate",
            f"Keyboard traversal did not complete ({result.incomplete_reason or 'unknown'}); "
            "operability could not be determined.",
            page_state_hash=page_state_hash,
            details={"cycles_completed": result.cycles_completed},
        )

    blockers = [
        u for u in result.unreached
        if u.reason in (UnreachedReason.NOT_FOCUSABLE, UnreachedReason.OBSCURED)
    ]
    blind_spots = [
        u for u in result.unreached
        if u.reason in (UnreachedReason.SHADOW_DOM, UnreachedReason.IFRAME, UnreachedReason.UNKNOWN)
    ]
    # ARROW_NAVIGABLE is deliberately in neither list. It is correct authoring,
    # not a barrier and not a blind spot, so it does not affect the verdict.

    if blockers:
        return _finding(
            "2.1.1", "fail",
            f"{len(blockers)} interactive element(s) could not be reached by keyboard.",
            page_state_hash=page_state_hash,
            selector=blockers[0].selector,
            details={"unreachable": [u.selector for u in blockers]},
            severity=Severity.CRITICAL,
        )

    if blind_spots:
        # We did not look everywhere. Saying "pass" would be a claim we
        # cannot support.
        return _finding(
            "2.1.1", "indeterminate",
            f"{len(blind_spots)} region(s) were not traversed "
            f"({', '.join(sorted({u.reason.value for u in blind_spots}))}); "
            "keyboard operability is unverified there.",
            page_state_hash=page_state_hash,
            details={"unvisited": [u.selector for u in blind_spots]},
        )

    if not result.stops:
        # A page with no tab stops at all is more likely a traversal that
        # never started than a page with no interactive content.
        return _finding(
            "2.1.1", "indeterminate",
            "No tab stops were observed; the page may have no interactive "
            "content, or the traversal may not have started.",
            page_state_hash=page_state_hash,
        )

    return _finding(
        "2.1.1", "pass",
        f"All {len(result.stops)} observed interactive element(s) are reachable by keyboard.",
        page_state_hash=page_state_hash,
        details={"stops": len(result.stops)},
    )


def judge_no_keyboard_trap(result: TraversalResult, page_state_hash: str) -> Finding:
    """
    **SC 2.1.2 No Keyboard Trap** — can focus always move away again?

    Track A owns detection (A4.2) and asserts a trap only after N full
    cycles, with N determined by measurement. Track B reads that verdict and
    does not second-guess it.

    The asymmetry that matters: a trap that *was* detected is a definite
    failure, but a trap that was *not* detected is only a pass if the
    traversal ran its full course. Fewer cycles than requested means we
    stopped looking early, and a trap found on cycle 3 is invisible to a
    2-cycle run.
    """
    if result.trap_detected:
        return _finding(
            "2.1.2", "fail",
            f"Keyboard trap: focus could not be moved away from "
            f"{result.trap_selector or 'an element'} using the keyboard alone.",
            page_state_hash=page_state_hash,
            selector=result.trap_selector,
            trace=[s.selector for s in result.stops[-8:]],
            details={"cycles_completed": result.cycles_completed},
            severity=Severity.CRITICAL,
        )

    if not result.complete or result.cycles_completed < result.cycles_requested:
        return _finding(
            "2.1.2", "indeterminate",
            f"Completed {result.cycles_completed} of {result.cycles_requested} "
            "traversal cycles; a trap occurring later would not have been seen.",
            page_state_hash=page_state_hash,
            details={
                "cycles_requested": result.cycles_requested,
                "cycles_completed": result.cycles_completed,
            },
        )

    if not result.returned_to_origin:
        # Focus went somewhere we did not follow — browser chrome, a new
        # document. Not proof of a trap, not proof of its absence.
        return _finding(
            "2.1.2", "indeterminate",
            "Focus did not return to its starting point after a full cycle; "
            "it may have left the document.",
            page_state_hash=page_state_hash,
        )

    return _finding(
        "2.1.2", "pass",
        f"Focus moved freely through {result.cycles_completed} full cycle(s) "
        "and returned to its starting point.",
        page_state_hash=page_state_hash,
    )


def judge_focus_order(result: TraversalResult, page_state_hash: str) -> Finding:
    """
    **SC 2.4.3 Focus Order** — does focus order preserve meaning and operability?

    This is the judgment most likely to cry wolf, so it is deliberately
    narrow. "Meaningful order" is a human question; we do not attempt it.
    We report exactly one machine-checkable failure: **a positive `tabindex`**,
    which lifts an element out of document order and is the documented way to
    break focus order.

    A tab order that differs from DOM order is *not* on its own a failure —
    CSS reordering, dialogs and roving tabindex all do it legitimately. So a
    mismatch with no positive tabindex behind it is reported as a pass here,
    not as a suspicion.

    Note the order of the checks: a positive tabindex seen on a stop we
    actually visited is a fact about the page whether or not the traversal
    finished, so it is asserted before `complete` is consulted. Passing, by
    contrast, is a claim about every stop — including the ones we never
    reached — and so requires a complete traversal.
    """
    if not result.stops:
        return _finding(
            "2.4.3", "indeterminate",
            "No tab stops observed; focus order could not be assessed.",
            page_state_hash=page_state_hash,
        )

    positive = [s for s in result.stops if s.tabindex is not None and s.tabindex > 0]
    if positive:
        return _finding(
            "2.4.3", "fail",
            f"{len(positive)} element(s) use a positive tabindex, which removes them "
            "from document order and makes focus order depend on authored numbers.",
            page_state_hash=page_state_hash,
            selector=positive[0].selector,
            details={
                "positive_tabindex": [
                    {"selector": s.selector, "tabindex": s.tabindex} for s in positive
                ]
            },
        )

    unknown_tabindex = [s for s in result.stops if s.tabindex is None]
    if unknown_tabindex:
        return _finding(
            "2.4.3", "indeterminate",
            f"tabindex was not recorded for {len(unknown_tabindex)} stop(s); "
            "focus order could not be assessed.",
            page_state_hash=page_state_hash,
        )

    if not result.complete:
        return _finding(
            "2.4.3", "indeterminate",
            f"Traversal did not complete ({result.incomplete_reason or 'unknown'}); "
            "stops beyond the point it stopped were never inspected for a "
            "positive tabindex.",
            page_state_hash=page_state_hash,
        )

    return _finding(
        "2.4.3", "pass",
        "No positive tabindex values; focus order follows document order.",
        page_state_hash=page_state_hash,
    )


def judge_focus_visible(result: TraversalResult, page_state_hash: str) -> Finding:
    """
    **SC 2.4.7 Focus Visible** — is the keyboard focus indicator visible?

    `focus_visible` is three-valued on purpose. `None` means A4.3 did not
    measure this stop, and it is not the same as `False`. Collapsing the two
    would turn "we didn't look" into "there's no indicator" — a fabricated
    failure on every stop the screenshot diff happened to skip.

    As with focus order, a missing indicator observed on a stop we actually
    visited is a fact whether or not the traversal finished, so it is
    asserted first. A pass claims something about *every* stop on the page,
    so it requires a complete traversal — reporting 2.4.7 as satisfied
    because the handful of elements we reached before timing out happened to
    look fine is precisely the unearned claim this module exists to avoid.
    """
    if not result.stops:
        return _finding(
            "2.4.7", "indeterminate",
            "No tab stops observed; focus visibility could not be assessed.",
            page_state_hash=page_state_hash,
        )

    measured = [s for s in result.stops if s.focus_visible is not None]
    if not measured:
        return _finding(
            "2.4.7", "indeterminate",
            "Focus visibility was not measured for any tab stop.",
            page_state_hash=page_state_hash,
        )

    invisible = [s for s in measured if s.focus_visible is False]
    if invisible:
        return _finding(
            "2.4.7", "fail",
            f"{len(invisible)} element(s) show no visible focus indicator when focused.",
            page_state_hash=page_state_hash,
            selector=invisible[0].selector,
            details={"no_indicator": [s.selector for s in invisible]},
        )

    unmeasured = len(result.stops) - len(measured)
    if unmeasured:
        return _finding(
            "2.4.7", "indeterminate",
            f"{len(measured)} of {len(result.stops)} stops had a visible focus "
            f"indicator; the remaining {unmeasured} were not measured.",
            page_state_hash=page_state_hash,
            details={"measured": len(measured), "unmeasured": unmeasured},
        )

    if not result.complete:
        return _finding(
            "2.4.7", "indeterminate",
            f"Traversal did not complete ({result.incomplete_reason or 'unknown'}); "
            f"the {len(measured)} stop(s) reached all had a visible indicator, but "
            "the rest of the page was never focused.",
            page_state_hash=page_state_hash,
            details={"measured": len(measured)},
        )

    return _finding(
        "2.4.7", "pass",
        f"All {len(measured)} tab stop(s) show a visible focus indicator.",
        page_state_hash=page_state_hash,
    )


# --- B4.1: the whole mapping ------------------------------------------------

def map_traversal_to_findings(
    result: TraversalResult, page_state_hash: str
) -> list[Finding]:
    """
    One traversal in, four findings out — SC 2.1.1, 2.1.2, 2.4.3, 2.4.7.

    Always four, including passes. A keyboard checker that only emits
    failures cannot tell "this page is fine" from "we never checked", and
    the conformance map needs the difference.
    """
    return [
        judge_keyboard_operable(result, page_state_hash),
        judge_no_keyboard_trap(result, page_state_hash),
        judge_focus_order(result, page_state_hash),
        judge_focus_visible(result, page_state_hash),
    ]


def outcome_of(finding: Finding) -> Outcome:
    """Read a Finding back as one of the three B4.2 states."""
    if finding.outcome == "cantTell":
        return "indeterminate"
    return "pass" if finding.outcome == "pass" else "fail"


def is_indeterminate(findings: list[Finding]) -> bool:
    """True if any judgment came back undecided."""
    return any(f.outcome == "cantTell" for f in findings)


# --- B4.4: retry policy -----------------------------------------------------

DEFAULT_RETRY_CAP = 3


async def resolve_with_retries(
    run_traversal: Callable[[], Awaitable[TraversalResult]],
    page_state_hash: str,
    *,
    cap: int = DEFAULT_RETRY_CAP,
    delay_seconds: float = 0.0,
) -> tuple[list[Finding], int]:
    """
    Re-run the traversal while anything is still indeterminate, up to `cap`.

    Keyboard results are flaky in a way contrast results are not. A page that
    is still settling, a transition mid-flight, a lazily-hydrated widget —
    any of these produce an honest `indeterminate` on one run and a clean
    verdict on the next. Retrying converts noise into signal.

    Three rules the cap enforces:

    1. **Bounded.** `cap` is a hard ceiling on *total* attempts, so a page
       that is permanently undecidable costs a fixed amount of time rather
       than hanging CI.
    2. **Never retry a decision.** Once every judgment is pass or fail we
       stop immediately — re-running a settled page only invites flake.
    3. **Indeterminate is a legitimate final answer.** If the attempts run
       out we return the last result as-is. We do not escalate to `fail`
       because we got bored, and we do not downgrade to `pass` because
       nothing went wrong.

    Returns the findings plus the number of attempts actually made, so the
    report can say how hard we tried.
    """
    if cap < 1:
        raise ValueError("retry cap must be at least 1")

    findings: list[Finding] = []
    attempts = 0

    for attempt in range(1, cap + 1):
        attempts = attempt
        result = await run_traversal()
        findings = map_traversal_to_findings(result, page_state_hash)

        if not is_indeterminate(findings):
            break

        if attempt < cap:
            logger.info(
                "Keyboard traversal indeterminate on attempt %d/%d; retrying.",
                attempt,
                cap,
            )
            if delay_seconds:
                await asyncio.sleep(delay_seconds)

    if is_indeterminate(findings):
        logger.info(
            "Keyboard traversal still indeterminate after %d attempt(s); "
            "reporting as needs-review.",
            attempts,
        )

    for finding in findings:
        finding.evidence.computed_values["traversal_attempts"] = attempts

    return findings, attempts
