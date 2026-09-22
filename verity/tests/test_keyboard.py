"""
Tests for the keyboard judgments (B4.1, B4.2, B4.4).

Week 4's gate is "injected trap detected, **zero false alarms on clean APG
widgets**". Correctly-built widgets are the hard case: a tablist using
roving tabindex exposes one tab stop for six tabs, by design. So most of
these tests are about the checker keeping quiet.
"""

import pytest

from verity.agents.keyboard import (
    DEFAULT_RETRY_CAP,
    is_indeterminate,
    judge_focus_order,
    judge_focus_visible,
    judge_keyboard_operable,
    judge_no_keyboard_trap,
    map_traversal_to_findings,
    outcome_of,
    resolve_with_retries,
)
from verity.models.schemas import (
    Provenance,
    Modality,
    TabStop,
    TraversalResult,
    UnreachedReason,
    UnreachedRegion,
)

HASH = "page-state-abc"


def stop(order: int, selector: str, *, tabindex: int | None = 0,
         focus_visible: bool | None = True, cycle: int = 0) -> TabStop:
    return TabStop(
        order=order, selector=selector, cycle=cycle,
        tabindex=tabindex, focus_visible=focus_visible, dom_order=order,
    )


def clean_traversal(**overrides) -> TraversalResult:
    """A well-behaved page: three stops, two full cycles, nothing unreachable."""
    base = dict(
        stops=[stop(0, "#a"), stop(1, "#b"), stop(2, "#c")],
        cycles_requested=2,
        cycles_completed=2,
        returned_to_origin=True,
        trap_detected=False,
        unreached=[],
        complete=True,
    )
    base.update(overrides)
    return TraversalResult(**base)


# --- the gate: zero false alarms on clean pages ----------------------------

def test_clean_page_produces_four_passes_and_nothing_gating():
    findings = map_traversal_to_findings(clean_traversal(), HASH)

    assert [f.sc.id for f in findings] == ["2.1.1", "2.1.2", "2.4.3", "2.4.7"]
    assert all(f.outcome == "pass" for f in findings)
    assert all(f.provenance is Provenance.AUTHORITATIVE for f in findings)
    assert not any(f.outcome == "fail" for f in findings)


def test_roving_tabindex_widget_is_not_a_false_alarm():
    """
    An APG tablist with roving tabindex exposes ONE tab stop for the whole
    tablist — the other tabs carry tabindex="-1" and are reached with arrow
    keys. That is correct authoring. A checker that expects one stop per tab
    would fire here, and the plan calls that a design bug.
    """
    result = clean_traversal(
        stops=[
            stop(0, "#tablist [role=tab][aria-selected=true]", tabindex=0),
            stop(1, "#tabpanel", tabindex=0),
        ]
    )
    findings = map_traversal_to_findings(result, HASH)
    assert all(f.outcome == "pass" for f in findings)


def test_arrow_navigable_tabs_are_not_reported_as_unreachable():
    """
    The false alarm the tablist contract exists to prevent
    (`data/apg-contracts/tablist.yaml`).

    A correct tablist with six tabs exposes ONE Tab stop — the other five
    carry tabindex="-1" and are reached with arrow keys. Pressing only Tab
    does not prove they are unreachable, it proves we pressed the wrong key.
    Reporting them under SC 2.1.1 would fail the zero-false-alarms gate on a
    widget built exactly to spec.
    """
    result = clean_traversal(
        stops=[stop(0, "[role=tab][aria-selected=true]"), stop(1, "#panel")],
        unreached=[
            UnreachedRegion(selector=f"[role=tab]:nth-of-type({i})",
                            reason=UnreachedReason.ARROW_NAVIGABLE)
            for i in range(2, 7)
        ],
    )
    finding = judge_keyboard_operable(result, HASH)
    assert finding.outcome == "pass", "roving tabindex must not read as unreachable"
    assert finding.provenance is Provenance.AUTHORITATIVE


def test_arrow_navigable_does_not_mask_a_real_barrier():
    """The exemption is per-element, not a blanket amnesty for the page."""
    result = clean_traversal(
        unreached=[
            UnreachedRegion(selector="[role=tab]:nth-of-type(2)",
                            reason=UnreachedReason.ARROW_NAVIGABLE),
            UnreachedRegion(selector="#orphan-btn",
                            reason=UnreachedReason.NOT_FOCUSABLE),
        ]
    )
    finding = judge_keyboard_operable(result, HASH)
    assert finding.outcome == "fail"
    assert finding.evidence.dom_selector == "#orphan-btn"
    assert finding.evidence.computed_values["unreachable"] == ["#orphan-btn"]


def test_tab_order_differing_from_dom_order_is_not_by_itself_a_failure():
    """
    CSS reordering, dialogs and roving tabindex all legitimately make tab
    order differ from document order. Only a positive tabindex is asserted.
    """
    result = clean_traversal(
        stops=[
            TabStop(order=0, selector="#c", cycle=0, tabindex=0, focus_visible=True, dom_order=2),
            TabStop(order=1, selector="#a", cycle=0, tabindex=0, focus_visible=True, dom_order=0),
            TabStop(order=2, selector="#b", cycle=0, tabindex=0, focus_visible=True, dom_order=1),
        ]
    )
    assert judge_focus_order(result, HASH).outcome == "pass"


# --- SC 2.1.1 Keyboard ------------------------------------------------------

def test_unreachable_element_fails_211():
    result = clean_traversal(
        unreached=[UnreachedRegion(selector="#hidden-btn", reason=UnreachedReason.NOT_FOCUSABLE)]
    )
    finding = judge_keyboard_operable(result, HASH)
    assert finding.outcome == "fail"
    assert finding.provenance is Provenance.AUTHORITATIVE
    assert finding.evidence.dom_selector == "#hidden-btn"


def test_shadow_dom_blind_spot_is_indeterminate_not_a_failure():
    """
    A region we could not traverse is *our* limitation. Reporting it as a
    failure blames the page for our blind spot — a false positive.
    """
    result = clean_traversal(
        unreached=[UnreachedRegion(selector="my-widget", reason=UnreachedReason.SHADOW_DOM)]
    )
    finding = judge_keyboard_operable(result, HASH)
    assert finding.outcome == "cantTell"
    assert finding.provenance is Provenance.NEEDS_REVIEW


def test_incomplete_traversal_is_indeterminate_for_211():
    result = clean_traversal(complete=False, incomplete_reason="timeout")
    assert judge_keyboard_operable(result, HASH).outcome == "cantTell"


def test_no_stops_at_all_is_indeterminate_not_a_pass():
    """More likely a traversal that never started than a page with no controls."""
    result = clean_traversal(stops=[])
    assert judge_keyboard_operable(result, HASH).outcome == "cantTell"


# --- SC 2.1.2 No Keyboard Trap ---------------------------------------------

def test_detected_trap_fails_212():
    result = clean_traversal(trap_detected=True, trap_selector="#modal-input")
    finding = judge_no_keyboard_trap(result, HASH)
    assert finding.outcome == "fail"
    assert finding.provenance is Provenance.AUTHORITATIVE
    assert finding.evidence.dom_selector == "#modal-input"
    assert finding.evidence.interaction_trace  # the last few stops, as evidence


def test_fewer_cycles_than_requested_is_indeterminate_not_a_pass():
    """
    A trap that only manifests on cycle 3 is invisible to a 2-cycle run. Not
    finding one is only a pass if we actually looked as hard as we intended.
    """
    result = clean_traversal(cycles_requested=3, cycles_completed=2)
    assert judge_no_keyboard_trap(result, HASH).outcome == "cantTell"


def test_focus_leaving_the_document_is_indeterminate():
    result = clean_traversal(returned_to_origin=False)
    assert judge_no_keyboard_trap(result, HASH).outcome == "cantTell"


# --- SC 2.4.3 Focus Order ---------------------------------------------------

def test_positive_tabindex_fails_243():
    result = clean_traversal(
        stops=[stop(0, "#jumped", tabindex=99), stop(1, "#a"), stop(2, "#b")]
    )
    finding = judge_focus_order(result, HASH)
    assert finding.outcome == "fail"
    assert finding.evidence.dom_selector == "#jumped"
    assert finding.evidence.computed_values["positive_tabindex"][0]["tabindex"] == 99


@pytest.mark.parametrize("value", [0, -1])
def test_zero_and_negative_tabindex_are_legitimate(value):
    result = clean_traversal(stops=[stop(0, "#a", tabindex=value)])
    assert judge_focus_order(result, HASH).outcome == "pass"


def test_unrecorded_tabindex_is_indeterminate():
    """If Track A didn't record tabindex, we cannot assess focus order."""
    result = clean_traversal(stops=[stop(0, "#a", tabindex=None)])
    assert judge_focus_order(result, HASH).outcome == "cantTell"


# --- SC 2.4.7 Focus Visible -------------------------------------------------

def test_missing_indicator_fails_247():
    result = clean_traversal(
        stops=[stop(0, "#a"), stop(1, "#no-ring", focus_visible=False)]
    )
    finding = judge_focus_visible(result, HASH)
    assert finding.outcome == "fail"
    assert finding.evidence.dom_selector == "#no-ring"


def test_unmeasured_is_not_the_same_as_invisible():
    """
    focus_visible=None means "not measured"; False means "measured, nothing
    there". Collapsing them fabricates a failure on every stop A4.3 skipped.
    """
    result = clean_traversal(stops=[stop(0, "#a", focus_visible=None)])
    finding = judge_focus_visible(result, HASH)
    assert finding.outcome == "cantTell"
    assert finding.provenance is Provenance.NEEDS_REVIEW


def test_partially_measured_is_indeterminate_not_a_pass():
    result = clean_traversal(
        stops=[stop(0, "#a", focus_visible=True), stop(1, "#b", focus_visible=None)]
    )
    assert judge_focus_visible(result, HASH).outcome == "cantTell"


# --- evidence stands alone; a pass needs complete coverage -----------------
#
# The rule these four tests pin down: observing a defect is a fact about the
# page whether or not the traversal finished, so it is asserted regardless.
# Passing is a claim about *every* stop, including the ones never reached, so
# it requires `complete=True`. An earlier version of judge_focus_visible got
# this backwards and reported SC 2.4.7 as satisfied on a traversal that died
# halfway, based only on the handful of stops it managed to reach.

@pytest.mark.parametrize(
    "judge,sc_id",
    [
        (judge_keyboard_operable, "2.1.1"),
        (judge_no_keyboard_trap, "2.1.2"),
        (judge_focus_order, "2.4.3"),
        (judge_focus_visible, "2.4.7"),
    ],
)
def test_no_judgment_passes_on_an_incomplete_traversal(judge, sc_id):
    """A clean-looking partial traversal must never produce a pass."""
    result = clean_traversal(complete=False, incomplete_reason="timeout")
    finding = judge(result, HASH)
    assert finding.outcome != "pass", (
        f"SC {sc_id} claimed a pass from a traversal that never finished"
    )
    assert finding.outcome == "cantTell"


def test_real_defects_are_still_reported_from_a_partial_traversal():
    """
    The other half of the rule. A positive tabindex, a missing indicator or a
    detected trap seen before the traversal died are all still true, and
    downgrading them to cantTell would lose a real finding.
    """
    partial = dict(complete=False, incomplete_reason="timeout")

    trapped = clean_traversal(trap_detected=True, trap_selector="#x", **partial)
    assert judge_no_keyboard_trap(trapped, HASH).outcome == "fail"

    bad_order = clean_traversal(stops=[stop(0, "#jumped", tabindex=7)], **partial)
    assert judge_focus_order(bad_order, HASH).outcome == "fail"

    no_ring = clean_traversal(stops=[stop(0, "#no-ring", focus_visible=False)], **partial)
    assert judge_focus_visible(no_ring, HASH).outcome == "fail"


# --- B4.2: the three states -------------------------------------------------

def test_indeterminate_never_gates_and_never_claims_confidence():
    """
    cli.py exits non-zero only on authoritative failures. No indeterminate
    branch may reach that state, and none may claim confidence it lacks.
    """
    undecidable = TraversalResult(
        stops=[], cycles_requested=2, cycles_completed=0,
        complete=False, incomplete_reason="worker timeout",
    )
    findings = map_traversal_to_findings(undecidable, HASH)

    assert is_indeterminate(findings)
    for f in findings:
        assert f.outcome == "cantTell"
        assert f.provenance is Provenance.NEEDS_REVIEW
        assert f.confidence.score == 0.0
        assert not (f.provenance is Provenance.AUTHORITATIVE and f.outcome == "fail")


def test_outcome_of_round_trips_the_three_states():
    findings = map_traversal_to_findings(clean_traversal(), HASH)
    assert {outcome_of(f) for f in findings} == {"pass"}

    trapped = map_traversal_to_findings(
        clean_traversal(trap_detected=True, trap_selector="#x"), HASH
    )
    assert outcome_of(next(f for f in trapped if f.sc.id == "2.1.2")) == "fail"


def test_findings_are_tagged_as_interaction_modality():
    for f in map_traversal_to_findings(clean_traversal(), HASH):
        assert f.sc.modality is Modality.INTERACTION
        assert f.agent == "keyboard"


def test_finding_ids_are_reproducible():
    a = map_traversal_to_findings(clean_traversal(), HASH)
    b = map_traversal_to_findings(clean_traversal(), HASH)
    assert [f.id for f in a] == [f.id for f in b]


# --- B4.4: retry policy -----------------------------------------------------

@pytest.mark.asyncio
async def test_retry_stops_as_soon_as_everything_is_decided():
    """Re-running a settled page only invites flake."""
    calls = 0

    async def run():
        nonlocal calls
        calls += 1
        return clean_traversal()

    findings, attempts = await resolve_with_retries(run, HASH, cap=3)
    assert calls == 1
    assert attempts == 1
    assert all(f.outcome == "pass" for f in findings)


@pytest.mark.asyncio
async def test_retry_recovers_a_page_that_was_still_settling():
    """One flaky run, then a clean one — exactly what retries are for."""
    calls = 0

    async def run():
        nonlocal calls
        calls += 1
        if calls == 1:
            return clean_traversal(complete=False, incomplete_reason="still settling")
        return clean_traversal()

    findings, attempts = await resolve_with_retries(run, HASH, cap=3)
    assert calls == 2
    assert attempts == 2
    assert not is_indeterminate(findings)


@pytest.mark.asyncio
async def test_retry_is_capped_and_indeterminate_is_a_valid_final_answer():
    """
    Running out of attempts must not escalate to `fail` or downgrade to
    `pass`. A permanently undecidable page costs a fixed amount of time and
    is reported honestly.
    """
    calls = 0

    async def run():
        nonlocal calls
        calls += 1
        return clean_traversal(complete=False, incomplete_reason="never settles")

    findings, attempts = await resolve_with_retries(run, HASH, cap=3)
    assert calls == 3
    assert attempts == 3
    assert is_indeterminate(findings)
    assert all(f.outcome == "cantTell" for f in findings)
    assert not any(f.outcome == "fail" for f in findings)


@pytest.mark.asyncio
async def test_attempt_count_is_recorded_on_the_findings():
    async def run():
        return clean_traversal(complete=False)

    findings, attempts = await resolve_with_retries(run, HASH, cap=2)
    assert attempts == 2
    assert all(f.evidence.computed_values["traversal_attempts"] == 2 for f in findings)


@pytest.mark.asyncio
async def test_cap_must_be_at_least_one():
    async def run():
        return clean_traversal()

    with pytest.raises(ValueError, match="at least 1"):
        await resolve_with_retries(run, HASH, cap=0)


def test_default_cap_is_bounded():
    assert 1 <= DEFAULT_RETRY_CAP <= 5
