"""
BC-A1 — the keyboard wedge, end to end through `scan_url()`.

`test_keyboard.py` tests the four judges against hand-built `TraversalResult`
objects. `test_traverse.py` tests that the worker's payload validates as one.
Neither proves a `verity scan` actually *emits* keyboard findings — which was
exactly the gap BC-A1 names: the wedge was "built and tested" and still dark
on the command line.

So these drive the **real worker through the real pipeline** and assert on the
`AuditReport`. They are the Week 4 gate — *injected trap detected, zero false
alarms on clean APG widgets* — measured at the level a user experiences.

Skipped when the worker isn't built, like the other integration tests, so the
Python-only CI job doesn't fail on a missing `dist/`.
"""

from pathlib import Path

import pytest

from verity.models.schemas import AuditReport, Provenance

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"
FIXTURES = REPO / "data" / "fixtures"

pytestmark = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


async def scan_fixture(name: str) -> AuditReport:
    from verity.orchestrator.main import scan_url

    return await scan_url(
        (FIXTURES / name).as_uri(),
        node_worker_command=["node", str(WORKER_JS)],
        timeout=90.0,
    )


def keyboard_findings(report: AuditReport, sc_id: str | None = None) -> list:
    out = [f for f in report.findings if f.agent == "keyboard"]
    if sc_id is not None:
        out = [f for f in out if f.sc.id == sc_id]
    return out


def outcome_for(report: AuditReport, sc_id: str) -> str | None:
    found = keyboard_findings(report, sc_id)
    return found[0].outcome if found else None


# --- the wiring actually happened -----------------------------------------

@pytest.mark.asyncio
async def test_a_scan_emits_keyboard_findings_at_all():
    """
    The BC-A1 regression guard. Before the wiring a `verity scan` produced
    **zero** keyboard findings on every page, no matter what was wrong with
    it. If this fails, the traversal has silently stopped being called and
    the differentiator is dark again.
    """
    report = await scan_fixture("keyboard-tablist.html")
    found = keyboard_findings(report)

    assert found, "scan_url produced no keyboard findings — BC-A1 is unwired"
    assert {f.sc.id for f in found} == {"2.1.1", "2.1.2", "2.4.3", "2.4.7"}, (
        "all four criteria should be reported, including passes — a checker "
        "that only emits failures cannot tell 'fine' from 'never checked'"
    )


@pytest.mark.asyncio
async def test_focus_visible_is_actually_measured():
    """
    The `measureFocusVisible=True` decision, verified rather than assumed.

    Left off, every `focus_visible` is `None` and SC 2.4.7 is permanently
    `cantTell` — a criterion that never produces a verdict. This asserts the
    flag is reaching the worker.
    """
    report = await scan_fixture("keyboard-tablist.html")
    assert outcome_for(report, "2.4.7") in ("pass", "fail"), (
        "SC 2.4.7 came back undecided — measureFocusVisible is not reaching "
        "the worker, or A4.3's diff found nothing to measure"
    )


# --- zero false alarms on a clean widget ----------------------------------

@pytest.mark.asyncio
async def test_clean_apg_tablist_raises_no_keyboard_failure():
    """
    Half the Week 4 gate, at scan level. A correct APG tablist with six tabs
    exposes one Tab stop; the other five carry `tabindex="-1"` and move under
    the arrow keys. Reporting those as unreachable would fail a widget built
    exactly to spec.

    This is the test that would have caught the bug writing
    `data/apg-contracts/tablist.yaml` surfaced — the one `ARROW_NAVIGABLE`
    exists to prevent.
    """
    report = await scan_fixture("keyboard-tablist.html")

    failures = [f for f in keyboard_findings(report) if f.outcome == "fail"]
    assert failures == [], (
        "false alarm on a correct APG widget: "
        f"{[(f.sc.id, f.message) for f in failures]}"
    )

    assert outcome_for(report, "2.1.1") == "pass", (
        "the five roving-tabindex tabs must read as ARROW_NAVIGABLE, not as "
        "unreachable controls"
    )


@pytest.mark.asyncio
async def test_a_clean_widget_produces_nothing_that_gates_the_build():
    """
    The user-visible consequence: a correct page must exit 0. Asked of the
    real policy rather than a re-implemented filter.
    """
    from verity.report.policy import DEFAULT_POLICY

    report = await scan_fixture("keyboard-tablist.html")
    gating = [f for f in DEFAULT_POLICY.gating_findings(report.findings)
              if f.agent == "keyboard"]
    assert gating == [], f"a clean widget would fail CI: {[f.sc.id for f in gating]}"


# --- the injected defects are caught --------------------------------------

@pytest.mark.asyncio
async def test_injected_keyboard_trap_fails_sc_212():
    """The other half of the gate: the trap must actually be detected."""
    report = await scan_fixture("keyboard-trap.html")

    trap = keyboard_findings(report, "2.1.2")
    assert trap, "no SC 2.1.2 finding at all"
    assert trap[0].outcome == "fail", (
        f"keyboard trap not detected (got {trap[0].outcome}): {trap[0].message}"
    )
    assert trap[0].provenance is Provenance.AUTHORITATIVE, (
        "a detected trap is a deterministic verdict and must be able to gate"
    )
    # Naming the element is what makes the finding actionable.
    assert trap[0].evidence.dom_selector, "the trapping element is not named"


@pytest.mark.asyncio
async def test_positive_tabindex_fails_sc_243():
    """
    The one machine-checkable focus-order failure we assert. Requires the
    worker to report the **authored** tabindex (5), not the computed one —
    if it sent the computed value, every focusable element would look
    positive and this judge would be unusable.
    """
    report = await scan_fixture("keyboard-positive-tabindex.html")

    order = keyboard_findings(report, "2.4.3")
    assert order, "no SC 2.4.3 finding at all"
    assert order[0].outcome == "fail", (
        f"positive tabindex not caught (got {order[0].outcome})"
    )

    reported = order[0].evidence.computed_values.get("positive_tabindex", [])
    assert reported, "the offending element is not recorded"
    assert reported[0]["tabindex"] == 5, (
        f"expected the authored tabindex 5, got {reported[0]['tabindex']} — "
        "the worker may be sending the computed value"
    )


@pytest.mark.asyncio
async def test_a_genuine_barrier_fails_sc_211():
    """
    `NOT_FOCUSABLE` — a real barrier, as distinct from the roving-tabindex
    and shadow-DOM cases that must *not* be reported. The button is visible
    and enabled but sits inside an `inert` subtree.
    """
    report = await scan_fixture("keyboard-unreachable.html")

    operable = keyboard_findings(report, "2.1.1")
    assert operable, "no SC 2.1.1 finding at all"
    assert operable[0].outcome == "fail", (
        f"the inert button was not reported unreachable (got "
        f"{operable[0].outcome}): {operable[0].message}"
    )


@pytest.mark.asyncio
async def test_an_injected_defect_does_gate_the_build():
    """The mirror of the clean-widget test: a real trap must exit non-zero."""
    from verity.report.policy import DEFAULT_POLICY

    report = await scan_fixture("keyboard-trap.html")
    gating = DEFAULT_POLICY.gating_findings(report.findings)
    assert any(f.sc.id == "2.1.2" for f in gating), (
        "a keyboard trap did not gate the build"
    )


# --- keyboard findings are first-class citizens ---------------------------

@pytest.mark.asyncio
async def test_keyboard_findings_go_through_the_normal_machinery():
    """
    They are appended to the same list as the axe findings, so dedup,
    severity, provenance coherence and the conformance map all treat them
    identically. That is the point of having one `Finding` model, and it is
    worth asserting rather than assuming.
    """
    report = await scan_fixture("keyboard-trap.html")
    trap = keyboard_findings(report, "2.1.2")[0]

    # Provenance coherence (B6.2) survived the round trip.
    assert trap.revalidate() is not None
    # Severity came from the shared policy (B6.3), not a hardcoded value:
    # 2.1.2 is a blocking criterion at level A.
    assert trap.severity.value == "critical"
    # It reached the conformance map.
    assert report.conformance.get("2.1.2") == "fail"
    # And it survives serialisation, which is what the report consumer reads.
    assert AuditReport.model_validate_json(report.model_dump_json()).findings


@pytest.mark.asyncio
async def test_keyboard_findings_appear_in_sarif():
    """
    End of the chain: a keyboard trap has to reach the format GitHub reads,
    or the differentiator is still invisible to a user in CI.
    """
    from verity.report import build_sarif

    report = await scan_fixture("keyboard-trap.html")
    doc = build_sarif(report)

    rules = {r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]}
    assert any("keyboard" in r for r in rules), (
        f"no keyboard rule in the SARIF output; rules were {rules}"
    )

    trap_results = [
        r for r in doc["runs"][0]["results"] if "keyboard-212" in r["ruleId"]
    ]
    assert trap_results, "the trap did not reach SARIF"
    assert trap_results[0]["level"] == "error", (
        "an authoritative keyboard failure must be a SARIF error"
    )
