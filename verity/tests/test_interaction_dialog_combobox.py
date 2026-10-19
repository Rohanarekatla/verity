"""
Week 9, Track B — the dialog and combobox contracts, without a browser.

Hand-built snapshot sequences that mirror data/fixtures/apg/{dialog,combobox}-
{pass,fail}.html, plus the false-alarm cases each contract's YAML calls out:
a non-modal dialog, focus leaving to the browser's own UI, a lazily-rendered
popup, a search box that needs typing. The browser round trip is
test_contract_gate.py; the injected-misuse half of the gate is
test_aria_misuse.py.
"""

from typing import Optional

import pytest

from verity.agents.interaction import CHECKS, ContractRun, _watch, matches, run_contracts
from verity.models.schemas import ExerciseResult, InteractionSnapshot, Widget, WidgetInventory, WidgetNode
from verity.rulepacks import Severity, load_contracts


def wn(selector: str, role: Optional[str] = "button", tag: str = "button", name: Optional[str] = "Label",
       hidden: bool = False, tabindex: Optional[int] = None, **attrs) -> WidgetNode:
    return WidgetNode(selector=selector, tag=tag, role=role, accessible_name=name, tabindex=tabindex,
                      attributes={k.replace("_", "-"): v for k, v in attrs.items()}, hidden=hidden)


def exercise_returning(snapshots: list[InteractionSnapshot]):
    seen = {}

    async def exercise(widget, steps, watch, budget):
        seen["watch"] = watch
        seen["steps"] = steps
        return ExerciseResult(snapshots=snapshots, steps_requested=len(steps),
                              steps_run=max(0, len(snapshots) - 1), complete=bool(snapshots))
    exercise.seen = seen
    return exercise


def only(name: str):
    return {name: load_contracts()[name]}


def results(run: ContractRun) -> dict:
    return {r.assertion_id: r for r in run.results}


# --- dialog --------------------------------------------------------------------

def trigger(**over) -> WidgetNode:
    attrs = {"id": "t", "aria_haspopup": "dialog", "aria_controls": "dlg"}
    attrs.update(over)
    return wn("#t", name="Add delivery address", **attrs)


def dialog_node(open_: bool = False, modal: bool = True) -> WidgetNode:
    attrs = {"id": "dlg", "aria_labelledby": "ttl"}
    if modal:
        attrs["aria_modal"] = "true"
    return wn("#dlg", role="dialog", tag="div", name="Delivery address", hidden=not open_, **attrs)


def dialog_widget(modal: bool = True, **trigger_over) -> Widget:
    return Widget(root=trigger(**trigger_over), related=[dialog_node(modal=modal)])


def dsnap(i: int, active: Optional[str], open_: bool, inside: bool, modal: bool = True) -> InteractionSnapshot:
    return InteractionSnapshot(
        step_index=i, active=active,
        states=[trigger(), dialog_node(open_, modal)],
        missing=[] if inside else ["#dlg:focus-within"],
    )


def dialog_pass_snaps(modal: bool = True) -> list[InteractionSnapshot]:
    seq = [(-1, None, False, False), (0, "#t", False, False), (1, "#street", True, True),
           (2, "#save", True, True), (3, "#cancel", True, True), (4, "#street", True, True),
           (5, "#cancel", True, True), (6, "#t", False, False), (7, "#t", False, False),
           (8, "#street", True, True), (9, "#t", False, False), (10, "#street", True, True),
           (11, "#t", False, False)]
    return [dsnap(i, a, o, ins, modal) for i, a, o, ins in seq]


def test_dialog_contract_matches_only_dialog_triggers():
    contracts = load_contracts()
    d = Widget(root=trigger())
    assert matches(contracts["dialog"].match, d)
    assert not matches(contracts["menu-button"].match, d)
    assert not matches(contracts["disclosure"].match, d)


def test_dialog_watches_focus_within_the_dialog():
    assert "#dlg:focus-within" in _watch(dialog_widget(), CHECKS["dialog"])


@pytest.mark.asyncio
async def test_textbook_modal_dialog_passes_everything():
    run = await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                              exercise_returning(dialog_pass_snaps()), only("dialog"))
    bad = [(r.assertion_id, r.outcome, r.detail) for r in run.results if r.outcome != "pass"]
    assert bad == []


@pytest.mark.asyncio
async def test_dialog_that_leaves_focus_on_the_trigger_fails():
    snaps = dialog_pass_snaps()
    snaps[2] = dsnap(1, "#t", True, False)  # opened, focus still on the trigger
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                                    exercise_returning(snaps), only("dialog")))
    assert r["focus-moves-into-dialog"].outcome == "fail"
    assert r["focus-moves-into-dialog"].severity is Severity.VIOLATION
    assert r["tab-stays-in-modal-dialog"].outcome == "cantTell", "its precondition was never met"


@pytest.mark.asyncio
async def test_tab_walking_out_of_a_modal_dialog_fails():
    snaps = dialog_pass_snaps()
    snaps[4] = dsnap(3, "#after", True, False)  # Tab reached the page behind the overlay
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                                    exercise_returning(snaps), only("dialog")))
    assert r["tab-stays-in-modal-dialog"].outcome == "fail"
    assert "#after" in r["tab-stays-in-modal-dialog"].detail


@pytest.mark.asyncio
async def test_focus_going_to_the_browser_ui_is_not_an_escape():
    """A native <dialog> showModal() sends focus to the address bar at the end of the cycle."""
    snaps = dialog_pass_snaps()
    snaps[5] = dsnap(4, None, True, False)
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                                    exercise_returning(snaps), only("dialog")))
    assert r["tab-stays-in-modal-dialog"].outcome == "pass"


@pytest.mark.asyncio
async def test_a_non_modal_dialog_may_let_tab_leave():
    snaps = dialog_pass_snaps(modal=False)
    snaps[4] = dsnap(3, "#after", True, False, modal=False)
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget(modal=False)]),
                                    exercise_returning(snaps), only("dialog")))
    assert r["tab-stays-in-modal-dialog"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_click_only_dialog_trigger_fails_enter_and_space():
    seq = [(-1, None, False, False), (0, "#t", False, False), (1, "#t", False, False),
           (2, "#after", False, False), (3, "#before", False, False), (4, "#t", False, False),
           (5, "#before", False, False), (6, "#before", False, False), (7, "#t", False, False),
           (8, "#t", False, False), (9, "#t", False, False), (10, "#street", True, True),
           (11, "#t", False, False)]
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                                    exercise_returning([dsnap(*s) for s in seq]), only("dialog")))
    assert r["enter-opens-dialog"].outcome == "fail"
    assert r["space-opens-dialog"].outcome == "fail"
    assert r["focus-moves-into-dialog"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_missing_escape_is_a_warning_not_a_gate():
    snaps = dialog_pass_snaps()
    snaps[7] = dsnap(6, "#street", True, True)  # Escape did nothing
    r = results(await run_contracts(WidgetInventory(widgets=[dialog_widget()]),
                                    exercise_returning(snaps), only("dialog")))
    assert r["escape-closes-dialog"].outcome == "fail"
    assert r["escape-closes-dialog"].severity is Severity.WARNING


@pytest.mark.asyncio
async def test_without_aria_controls_the_dialog_checks_are_cantTell_not_fail():
    w = Widget(root=wn("#t", id="t", aria_haspopup="dialog"))
    run = await run_contracts(WidgetInventory(widgets=[w]), exercise_returning([]), only("dialog"))
    r = results(run)
    assert r["controls-a-dialog"].outcome == "cantTell"
    assert all(x.outcome in ("pass", "cantTell") for x in run.results)


@pytest.mark.asyncio
async def test_a_native_dialog_element_counts_as_a_dialog():
    native = wn("#dlg", role=None, tag="dialog", name="Delivery address", hidden=True,
                id="dlg", aria_labelledby="ttl")
    w = Widget(root=trigger(), related=[native])
    run = await run_contracts(WidgetInventory(widgets=[w]), exercise_returning([]), only("dialog"))
    assert results(run)["controls-a-dialog"].outcome == "pass"


# --- combobox ------------------------------------------------------------------

def combo_root(expanded: str = "false", tag: str = "input", ad: Optional[str] = None, **over) -> WidgetNode:
    attrs = {"id": "state", "aria_expanded": expanded, "aria_controls": "lb"}
    if ad:
        attrs["aria_activedescendant"] = ad
    attrs.update(over)
    return wn("#state", role="combobox", tag=tag, name="State", tabindex=0 if tag == "div" else None, **attrs)


def listbox(open_: bool) -> WidgetNode:
    return wn("#lb", role="listbox", tag="ul", name="States", hidden=not open_, id="lb")


OPTIONS = [wn("#o1", role="option", tag="li", name="Alabama", hidden=True, id="o1"),
           wn("#o2", role="option", tag="li", name="Alaska", hidden=True, id="o2")]


def combo_widget(tag: str = "input", lazy: bool = False, **over) -> Widget:
    return Widget(root=combo_root(tag=tag, **over), items=[] if lazy else OPTIONS,
                  related=[] if lazy else [listbox(False)])


def csnap(i: int, active: Optional[str], open_: bool, ad: Optional[str] = None, tag: str = "input",
          lazy: bool = False) -> InteractionSnapshot:
    states = [combo_root("true" if open_ else "false", tag=tag, ad=ad)]
    if not (lazy and not open_):
        states.append(listbox(open_))
    return InteractionSnapshot(step_index=i, active=active, states=states)


def combo_pass_snaps(lazy: bool = False) -> list[InteractionSnapshot]:
    seq = [(-1, None, False, None), (0, "#state", False, None), (1, "#state", True, "o1"),
           (2, "#state", True, "o2"), (3, "#state", False, None), (4, "#state", False, None),
           (5, "#state", True, None), (6, "#state", False, None), (7, "#state", True, None),
           (8, "#state", False, None)]
    return [csnap(i, a, o, ad, lazy=lazy) for i, a, o, ad in seq]


def test_combobox_watches_its_popup_by_id():
    assert '[id="lb"]' in _watch(combo_widget(), CHECKS["combobox"])


@pytest.mark.asyncio
async def test_textbook_editable_combobox_passes_everything():
    run = await run_contracts(WidgetInventory(widgets=[combo_widget()]),
                              exercise_returning(combo_pass_snaps()), only("combobox"))
    bad = [(r.assertion_id, r.outcome, r.detail) for r in run.results if r.outcome != "pass"]
    assert bad == []


@pytest.mark.asyncio
async def test_click_only_custom_select_fails_keyboard_opens_popup():
    seq = [(-1, None, False), (0, "#state", False), (1, "#state", False), (2, "#state", False),
           (3, "#state", False), (4, "#state", False), (5, "#state", False), (6, "#state", False),
           (7, "#state", True), (8, "#state", True)]
    snaps = [csnap(i, a, o, tag="div") for i, a, o in seq]
    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget(tag="div")]),
                                    exercise_returning(snaps), only("combobox")))
    assert r["keyboard-opens-popup"].outcome == "fail"
    assert r["keyboard-opens-popup"].severity is Severity.VIOLATION
    assert r["arrow-keys-reach-options"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_a_search_box_that_needs_typing_is_not_a_keyboard_failure():
    seq = [(i, "#state", False) for i in range(9)]
    snaps = [csnap(-1, None, False)] + [csnap(i, a, o) for i, a, o in seq]
    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget()]),
                                    exercise_returning(snaps), only("combobox")))
    assert r["keyboard-opens-popup"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_lazily_rendered_popup_is_found_once_it_opens():
    run = await run_contracts(WidgetInventory(widgets=[combo_widget(lazy=True)]),
                              exercise_returning(combo_pass_snaps(lazy=True)), only("combobox"))
    r = results(run)
    assert r["controls-a-popup"].outcome == "pass"
    assert r["keyboard-opens-popup"].outcome == "pass"
    assert r["options-have-names"].outcome == "cantTell"
    # Options were not in the DOM at scan time, so an activedescendant id cannot be verified.
    assert r["arrow-keys-reach-options"].outcome == "cantTell"


@pytest.mark.asyncio
async def test_lazy_popup_that_never_opens_is_cantTell_not_a_dangling_reference():
    seq = [(i, "#state", False) for i in range(9)]
    snaps = [csnap(-1, None, False, lazy=True)] + [csnap(i, a, o, lazy=True) for i, a, o in seq]
    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget(lazy=True)]),
                                    exercise_returning(snaps), only("combobox")))
    assert r["controls-a-popup"].outcome == "cantTell"


@pytest.mark.parametrize("tag, severity", [("div", Severity.VIOLATION), ("input", Severity.WARNING)])
@pytest.mark.asyncio
async def test_unreachable_options_gate_only_for_a_select_only_combobox(tag, severity):
    snaps = [csnap(i, a, o, None, tag=tag) for i, a, o, _ in
             [(-1, None, False, None), (0, "#state", False, None), (1, "#state", True, None),
              (2, "#state", True, None), (3, "#state", False, None), (4, "#state", False, None),
              (5, "#state", True, None), (6, "#state", False, None), (7, "#state", True, None),
              (8, "#state", False, None)]]
    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget(tag=tag)]),
                                    exercise_returning(snaps), only("combobox")))
    assert r["arrow-keys-reach-options"].outcome == "fail"
    assert r["arrow-keys-reach-options"].severity is severity


@pytest.mark.asyncio
async def test_absent_aria_expanded_is_reviewed_and_an_invalid_one_gates():
    w_absent = Widget(root=wn("#state", role="combobox", tag="input", name="State", id="state", aria_controls="lb"),
                      items=OPTIONS, related=[listbox(False)])
    r = results(await run_contracts(WidgetInventory(widgets=[w_absent]), exercise_returning([]), only("combobox")))
    assert r["aria-expanded-is-boolean"].outcome == "fail"
    assert r["aria-expanded-is-boolean"].severity is Severity.WARNING

    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget(aria_expanded="yes")]),
                                    exercise_returning([]), only("combobox")))
    assert r["aria-expanded-is-boolean"].severity is Severity.VIOLATION
    assert r["aria-expanded-is-boolean"].outcome == "fail"


@pytest.mark.asyncio
async def test_popup_shown_without_aria_expanded_true_fails():
    snaps = combo_pass_snaps()
    snaps[2] = InteractionSnapshot(step_index=1, active="#state",
                                   states=[combo_root("false", ad="o1"), listbox(True)])
    r = results(await run_contracts(WidgetInventory(widgets=[combo_widget()]),
                                    exercise_returning(snaps), only("combobox")))
    assert r["expanded-true-when-open"].outcome == "fail"
