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
        snap(3, "#btn", "true", False),
    )
    inv = WidgetInventory(widgets=[disclosure_widget()])
    run = await run_contracts(inv, ex, disclosure_only())
    r = by_id(run)
    assert all(x.outcome == "pass" for x in run.results), [(x.assertion_id, x.detail) for x in run.results]
    assert r["enter-toggles"].trace == ["focus #btn", "press 'Enter'", "press ' '", "click #btn"]


def keys_then_click(enter: bool, space: bool, click: bool):
    """Snapshots for focus, Enter, Space, click — each flipping aria-expanded or not."""
    state, snaps = "false", [snap(-1, None, "false", True), snap(0, "#btn", "false", True)]
    for i, flips in ((1, enter), (2, space), (3, click)):
        state = ("true" if state == "false" else "false") if flips else state
        snaps.append(snap(i, "#btn", state, state == "false"))
    return exercise_returning(*snaps)


@pytest.mark.asyncio
async def test_click_only_button_fails_enter_and_space():
    """Neither key works, a click does: the keyboard user is locked out."""
    run = await run_contracts(
        WidgetInventory(widgets=[disclosure_widget()]), keys_then_click(False, False, True), disclosure_only()
    )
    r = by_id(run)
    for aid in ("enter-toggles", "space-toggles"):
        assert r[aid].outcome == "fail" and r[aid].severity is Severity.VIOLATION, aid


@pytest.mark.asyncio
async def test_an_accordion_that_ignores_mouse_and_keyboard_alike_is_not_a_keyboard_failure():
    """github.com: the open header of a one-open accordion ignores Enter — and a click."""
    run = await run_contracts(
        WidgetInventory(widgets=[disclosure_widget()]), keys_then_click(False, False, False), disclosure_only()
    )
    r = by_id(run)
    assert r["enter-toggles"].outcome == "cantTell"
    assert r["space-toggles"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_space_failing_while_enter_works_is_an_apg_deviation_not_a_barrier():
    run = await run_contracts(
        WidgetInventory(widgets=[disclosure_widget()]), keys_then_click(True, False, True), disclosure_only()
    )
    r = by_id(run)
    assert r["enter-toggles"].outcome == "pass"
    assert r["space-toggles"].outcome == "fail"
    assert r["space-toggles"].severity is Severity.WARNING
    [f] = [f for f in to_findings(run, "h") if f.rule_id == "apg-disclosure-space-toggles"]
    assert f.provenance is Provenance.NEEDS_REVIEW, "an APG deviation must never gate"


@pytest.mark.asyncio
async def test_an_autoplaying_widget_is_not_judged_on_key_effects():
    """apple.com's gallery rotates by itself; a key's 'effect' may be the timer's."""
    ex = keys_then_click(False, False, True)
    inner = ex

    async def autoplaying(*args):
        return (await inner(*args)).model_copy(update={"self_changing": True})

    run = await run_contracts(WidgetInventory(widgets=[disclosure_widget()]), autoplaying, disclosure_only())
    r = by_id(run)
    assert r["enter-toggles"].outcome == "cantTell" and "on its own" in r["enter-toggles"].detail
    assert r["button-has-accessible-name"].outcome == "pass", "static checks still stand"


@pytest.mark.asyncio
async def test_widgets_not_rendered_are_not_judged():
    hidden = disclosure_widget()
    hidden.root.hidden = True
    ex = exercise_returning()
    run = await run_contracts(WidgetInventory(widgets=[hidden]), ex, disclosure_only())
    assert {r.outcome for r in run.results} == {"notChecked"}
    assert ex.calls == []


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


@pytest.mark.asyncio
async def test_every_tab_in_the_tab_order_is_un_idiomatic_not_a_barrier():
    """github.com's hero tabs: all reachable by Tab, so the failure never gates."""
    run = await run_contracts(
        WidgetInventory(widgets=[tablist([0, 0, 0])]), exercise_returning(),
        {"tablist": load_contracts()["tablist"]},
    )
    r = by_id(run)["roving-tabindex"]
    assert r.outcome == "fail" and r.severity is Severity.WARNING
    assert r.detail.startswith("APG deviation")


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


# --- regressions from the live APG reference implementations ---------------

@pytest.mark.asyncio
async def test_tabindex_minus_one_inside_a_roving_widget_is_not_a_failure():
    """
    APG "tabs with action buttons": the menu buttons inside the tablist carry
    tabindex=-1 and move under the arrow keys. Failing them as unreachable was
    a false alarm on a reference implementation.
    """
    roving = Widget(root=node("#act", aria_haspopup="true", tabindex=-1), roving_ancestor="#tablist")
    plain = Widget(root=node("#act2", aria_haspopup="true", tabindex=-1))
    run = await run_contracts(
        WidgetInventory(widgets=[roving, plain]), exercise_returning(),
        {"menu-button": load_contracts()["menu-button"]},
    )
    verdicts = {(r.widget, r.assertion_id): r.outcome for r in run.results}
    assert verdicts[("#act", "trigger-in-tab-sequence")] == "cantTell"
    # Outside a roving pattern too: tabindex=-1 alone does not prove a barrier
    # (stripe.com) — reachability is the tab-order traversal's call, not ours.
    assert verdicts[("#act2", "trigger-in-tab-sequence")] == "cantTell"


def menu_snap(i: int, active: str | None, menu_open: bool, activedescendant: str | None = None):
    menu_attrs = {"id": "menu"}
    if activedescendant:
        menu_attrs["aria_activedescendant"] = activedescendant
    return InteractionSnapshot(
        step_index=i, active=active,
        states=[
            node("#mb", aria_haspopup="true", aria_controls="menu",
                 **({"aria_expanded": "true"} if menu_open else {})),
            node("#menu", role="menu", hidden=not menu_open, **menu_attrs),
        ],
    )


@pytest.mark.asyncio
async def test_aria_activedescendant_counts_as_focus_on_the_item():
    """APG "menu button, aria-activedescendant": DOM focus stays on the menu."""
    items = [node(f"#mi{i}", role="menuitem", id=f"mi{i}") for i in (1, 2)]
    widget = Widget(
        root=node("#mb", aria_haspopup="true", aria_controls="menu"),
        items=items, related=[node("#menu", role="menu", id="menu", hidden=True)],
    )
    ex = exercise_returning(
        menu_snap(-1, None, False),
        menu_snap(0, "#mb", False),
        menu_snap(1, "#menu", True, "mi1"),
        menu_snap(2, "#menu", True, "mi2"),
        menu_snap(3, "#mb", False),
        menu_snap(4, "#menu", True, "mi1"),
        menu_snap(5, "#mb", False),
    )
    run = await run_contracts(WidgetInventory(widgets=[widget]), ex, {"menu-button": load_contracts()["menu-button"]})
    r = by_id(run)
    for aid in ("open-focuses-first-item", "arrow-down-moves-to-next-item",
                "escape-closes-and-returns-focus", "space-opens-menu", "items-use-managed-focus"):
        assert r[aid].outcome == "pass", (aid, r[aid].detail)
