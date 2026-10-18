"""
A9.1–A9.4 — the APG contract runner, without a browser.

The runner's honesty rules are what these pin: an assertion nobody
implemented is `notChecked`, never a pass; a run the budget cut short is
`cantTell`; a failed `warning` never becomes an authoritative finding; and the
A9.4 gate rejects a contract that cannot fail its own fail-fixture. The
browser round-trip is in test_contract_gate.py.
"""

from pathlib import Path

import pytest

from verity.agents.interaction import (
    ContractRun,
    InteractionBudget,
    AssertionResult,
    matches,
    run_contracts,
    to_findings,
    verify_contract_fixtures,
)
from verity.models.schemas import (
    ExerciseResult,
    InteractionSnapshot,
    Provenance,
    Widget,
    WidgetInventory,
    WidgetNode,
)
from verity.rulepacks import ApgContract, Severity, load_contracts


def node(selector: str, role: str | None = "button", **attrs) -> WidgetNode:
    tabindex = attrs.pop("tabindex", None)
    hidden = attrs.pop("hidden", False)
    name = attrs.pop("name", "Label")
    return WidgetNode(
        selector=selector, tag="button", role=role, accessible_name=name,
        tabindex=tabindex, attributes={k.replace("_", "-"): v for k, v in attrs.items()}, hidden=hidden,
    )


def disclosure_widget(**root_attrs) -> Widget:
    root_attrs.setdefault("aria_expanded", "false")
    root_attrs.setdefault("aria_controls", "panel")
    return Widget(
        root=node("#btn", **root_attrs),
        related=[node("#panel", role=None, id="panel", hidden=True)],
    )


def exercise_returning(*snapshots: InteractionSnapshot, complete: bool = True, reason=None):
    calls = []

    async def exercise(widget, steps, watch, budget):
        calls.append(steps)
        return ExerciseResult(
            snapshots=list(snapshots), steps_requested=len(steps),
            steps_run=max(0, len(snapshots) - 1), complete=complete, incomplete_reason=reason,
        )
    exercise.calls = calls
    return exercise


def snap(i: int, active: str | None, expanded: str, panel_hidden: bool) -> InteractionSnapshot:
    return InteractionSnapshot(
        step_index=i, active=active,
        states=[node("#btn", aria_expanded=expanded, aria_controls="panel"),
                node("#panel", role=None, id="panel", hidden=panel_hidden)],
    )


def by_id(run: ContractRun) -> dict[str, AssertionResult]:
    return {r.assertion_id: r for r in run.results}


def disclosure_only() -> dict[str, ApgContract]:
    return {"disclosure": load_contracts()["disclosure"]}


# --- matching ---------------------------------------------------------------

def test_match_by_role_and_attributes():
    w = disclosure_widget()
    assert matches({"role": "button", "has": ["aria-expanded"], "lacks": ["aria-haspopup"]}, w)
    assert not matches({"role": "tablist"}, w)
    assert not matches({"role": "button", "lacks": ["aria-expanded"]}, w)
    assert matches({"role": ["link", "button"]}, w)


def test_match_values_distinguishes_menu_buttons_from_other_popups():
    menu = Widget(root=node("#m", aria_haspopup="menu"))
    listbox = Widget(root=node("#l", aria_haspopup="listbox"))
    spec = {"role": "button", "values": {"aria-haspopup": ["true", "menu"]}}
    assert matches(spec, menu) and not matches(spec, listbox)


def test_unknown_match_key_is_an_error_not_a_match_everything():
    with pytest.raises(ValueError, match="unknown contract match key"):
        matches({"role": "button", "lack": ["aria-haspopup"]}, disclosure_widget())


def test_empty_match_matches_nothing():
    assert not matches({}, disclosure_widget())


def test_a_disclosure_is_not_judged_as_a_menu_button_and_vice_versa():
    contracts = load_contracts()
    disclosure, menu_button = contracts["disclosure"].match, contracts["menu-button"].match
    d = disclosure_widget()
    m = Widget(root=node("#m", aria_haspopup="true", aria_expanded="false"))
    assert matches(disclosure, d) and not matches(menu_button, d)
    assert matches(menu_button, m) and not matches(disclosure, m)


# --- verdicts ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_disclosure_that_toggles_on_enter_and_space_passes():
    ex = exercise_returning(
        snap(-1, None, "false", True),
        snap(0, "#btn", "false", True),
        snap(1, "#btn", "true", False),
        snap(2, "#btn", "false", True),
    )
    inv = WidgetInventory(widgets=[disclosure_widget()])
    run = await run_contracts(inv, ex, disclosure_only())
    r = by_id(run)
    assert all(x.outcome == "pass" for x in run.results), [(x.assertion_id, x.detail) for x in run.results]
    assert r["enter-toggles"].trace == ["focus #btn", "press 'Enter'", "press ' '"]


@pytest.mark.asyncio
async def test_click_only_button_fails_enter_and_space():
    ex = exercise_returning(
        snap(-1, None, "false", True),
        snap(0, "#btn", "false", True),
        snap(1, "#btn", "false", True),
        snap(2, "#btn", "false", True),
    )
    run = await run_contracts(WidgetInventory(widgets=[disclosure_widget()]), ex, disclosure_only())
    r = by_id(run)
    assert r["enter-toggles"].outcome == "fail"
    assert r["space-toggles"].outcome == "fail"


@pytest.mark.asyncio
async def test_a_run_cut_short_by_the_budget_is_cantTell_not_fail():
    """A9.3: the snapshots that never happened cannot be evidence of a defect."""
    ex = exercise_returning(
        snap(-1, None, "false", True),
        snap(0, "#btn", "false", True),
        complete=False, reason="interaction budget exhausted: 1 steps",
    )
    run = await run_contracts(WidgetInventory(widgets=[disclosure_widget()]), ex, disclosure_only())
    r = by_id(run)
    for aid in ("enter-toggles", "space-toggles", "focus-stays-on-button"):
        assert r[aid].outcome == "cantTell", aid
        assert "budget exhausted" in r[aid].detail


@pytest.mark.asyncio
async def test_focus_that_never_landed_is_cantTell():
    ex = exercise_returning(
        snap(-1, None, "false", True),
        snap(0, None, "false", True),
        snap(1, None, "false", True),
        snap(2, None, "false", True),
    )
    run = await run_contracts(WidgetInventory(widgets=[disclosure_widget()]), ex, disclosure_only())
    assert by_id(run)["enter-toggles"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_exercise_that_raises_leaves_driven_checks_cantTell_and_static_checks_decided():
    async def broken(*_):
        raise RuntimeError("worker too old: unknown method exerciseWidget")

    run = await run_contracts(WidgetInventory(widgets=[disclosure_widget()]), broken, disclosure_only())
    r = by_id(run)
    assert r["enter-toggles"].outcome == "cantTell"
    assert r["button-has-accessible-name"].outcome == "pass"


@pytest.mark.asyncio
async def test_every_assertion_gets_a_result_and_unimplemented_ones_are_notChecked():
    contract = ApgContract.model_validate({
        "contract": "imaginary", "version": 1, "match": {"role": "button"},
        "structure": [{"id": "a", "severity": "violation", "assert": "x"}],
        "keyboard": [{"id": "b", "severity": "warning", "assert": "y"}],
    })
    run = await run_contracts(
        WidgetInventory(widgets=[disclosure_widget()]), exercise_returning(), {"imaginary": contract}
    )
    assert [(r.assertion_id, r.outcome) for r in run.results] == [("a", "notChecked"), ("b", "notChecked")]


@pytest.mark.asyncio
async def test_check_code_drifting_from_its_contract_raises():
    """A verdict for an id the YAML no longer has is drift, not something to drop."""
    contract = load_contracts()["disclosure"].model_copy(deep=True)
    contract.keyboard = [a for a in contract.keyboard if a.id != "enter-toggles"]
    with pytest.raises(ValueError, match="enter-toggles"):
        await run_contracts(
            WidgetInventory(widgets=[disclosure_widget()]), exercise_returning(), {"disclosure": contract}
        )


@pytest.mark.asyncio
async def test_page_budget_skips_and_lists_widgets_beyond_the_cap():
    widgets = [disclosure_widget() for _ in range(3)]
    for i, w in enumerate(widgets):
        w.root.selector = f"#btn-{i}"
    ex = exercise_returning()
    run = await run_contracts(
        WidgetInventory(widgets=widgets), ex, disclosure_only(), InteractionBudget(max_widgets=2)
    )
    assert run.widgets_matched["disclosure"] == 3
    assert run.widgets_skipped == ["#btn-2"]
    assert len(ex.calls) == 2


@pytest.mark.asyncio
async def test_blind_spots_are_carried_into_the_run():
    run = await run_contracts(
        WidgetInventory(shadow_roots_skipped=2, iframes_skipped=1), exercise_returning(), disclosure_only()
    )
    assert (run.shadow_roots_skipped, run.iframes_skipped) == (2, 1)


# --- tablist static checks ---------------------------------------------------

def tablist(tabindexes: list[int | None]) -> Widget:
    tabs = [
        node(f"#t{i}", role="tab", tabindex=ti, id=f"t{i}", aria_controls=f"p{i}",
             aria_selected="true" if i == 0 else "false")
        for i, ti in enumerate(tabindexes)
    ]
    panels = [node(f"#p{i}", role="tabpanel", id=f"p{i}", aria_labelledby=f"t{i}", hidden=i != 0)
              for i in range(len(tabindexes))]
    return Widget(root=node("#tl", role="tablist"), items=tabs, related=panels)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tabindexes, expected",
    [([0, -1, -1], "pass"), ([None, -1, -1], "pass"), ([0, 0, 0], "fail"), ([None, None, -1], "fail")],
    ids=["roving", "native-first", "all-in-sequence", "two-native"],
)
async def test_roving_tabindex(tabindexes, expected):
    run = await run_contracts(
        WidgetInventory(widgets=[tablist(tabindexes)]), exercise_returning(),
        {"tablist": load_contracts()["tablist"]},
    )
    assert by_id(run)["roving-tabindex"].outcome == expected


# --- findings ----------------------------------------------------------------

def result(outcome: str, severity: Severity, section="keyboard", wcag=None) -> AssertionResult:
    return AssertionResult(
        contract="disclosure", assertion_id="x", severity=severity, wcag=wcag, section=section,
        widget="#btn", outcome=outcome, detail="d",
    )


@pytest.mark.parametrize(
    "outcome, severity, expected",
    [
        ("fail", Severity.VIOLATION, ("fail", Provenance.AUTHORITATIVE)),
        ("pass", Severity.VIOLATION, ("pass", Provenance.AUTHORITATIVE)),
        ("pass", Severity.WARNING, ("pass", Provenance.AUTHORITATIVE)),
        ("fail", Severity.WARNING, ("cantTell", Provenance.NEEDS_REVIEW)),
        ("cantTell", Severity.VIOLATION, ("cantTell", Provenance.NEEDS_REVIEW)),
    ],
)
def test_findings_mapping(outcome, severity, expected):
    [f] = to_findings(ContractRun(results=[result(outcome, severity, wcag="2.1.1")]), "hash")
    assert (f.outcome, f.provenance) == expected
    assert f.agent == "interaction"
    assert f.rule_id == "apg-disclosure-x"


def test_a_failed_warning_can_never_gate_a_build():
    [f] = to_findings(ContractRun(results=[result("fail", Severity.WARNING)]), "hash")
    assert not (f.provenance is Provenance.AUTHORITATIVE and f.outcome == "fail")
    assert f.confidence.score == 0.0


def test_notChecked_produces_no_finding():
    assert to_findings(ContractRun(results=[result("notChecked", Severity.VIOLATION)]), "hash") == []


def test_unpinned_sc_defaults_by_section():
    s, k = to_findings(ContractRun(results=[
        result("pass", Severity.VIOLATION, section="structure"),
        result("pass", Severity.VIOLATION, section="keyboard"),
    ]), "hash")
    assert (s.sc.id, k.sc.id) == ("4.1.2", "2.1.1")


# --- A9.4 gate, with a fake runner -------------------------------------------

def gate_contract(**overrides) -> dict[str, ApgContract]:
    data = {
        "contract": "disclosure", "version": 1, "match": {"role": "button"},
        "keyboard": [{"id": "enter-toggles", "severity": "violation", "assert": "x"}],
        "fixtures": {"pass": "apg/disclosure-pass.html", "fail": "apg/disclosure-fail.html"},
    }
    data.update(overrides)
    return {"disclosure": ApgContract.model_validate(data)}


def fake_runs(pass_outcome: str, fail_outcome: str, matched: int = 1):
    async def run_fixture(path: Path) -> ContractRun:
        outcome = pass_outcome if "pass" in path.name else fail_outcome
        return ContractRun(
            widgets_matched={"disclosure": matched},
            results=[result(outcome, Severity.VIOLATION)] if matched else [],
        )
    return run_fixture


@pytest.mark.asyncio
async def test_gate_accepts_a_contract_that_passes_clean_and_fails_broken():
    assert await verify_contract_fixtures(fake_runs("pass", "fail"), gate_contract()) == []


@pytest.mark.asyncio
async def test_gate_rejects_a_contract_that_cannot_fail_its_fail_fixture():
    problems = await verify_contract_fixtures(fake_runs("pass", "pass"), gate_contract())
    assert any("checks nothing" in p for p in problems)


@pytest.mark.asyncio
async def test_gate_rejects_a_false_alarm_on_the_pass_fixture():
    problems = await verify_contract_fixtures(fake_runs("fail", "fail"), gate_contract())
    assert any("false alarm" in p for p in problems)


@pytest.mark.asyncio
async def test_gate_rejects_an_undecided_violation_on_the_pass_fixture():
    problems = await verify_contract_fixtures(fake_runs("cantTell", "fail"), gate_contract())
    assert any("undecided" in p for p in problems)


@pytest.mark.asyncio
async def test_gate_rejects_fixtures_with_no_matching_widget():
    problems = await verify_contract_fixtures(fake_runs("pass", "fail", matched=0), gate_contract())
    assert any("no widget matching" in p for p in problems)


@pytest.mark.asyncio
async def test_gate_rejects_missing_or_undeclared_fixtures():
    missing = gate_contract(fixtures={"pass": "apg/nope.html", "fail": "apg/disclosure-fail.html"})
    assert any("missing" in p for p in await verify_contract_fixtures(fake_runs("pass", "fail"), missing))
    undeclared = gate_contract(fixtures=None)
    assert any("no fixtures" in p for p in await verify_contract_fixtures(fake_runs("pass", "fail"), undeclared))
