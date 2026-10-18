"""
verity/agents/interaction.py — the APG contract runner (A9.1–A9.4).

The worker reports what a widget is (`inventoryWidgets`, A9.2) and what
happened when keys were pressed on it (`exerciseWidget`, A9.1). This module
matches each inventoried widget to a hand-written contract in
`data/apg-contracts/` by its ARIA role, plans the key presses that contract
needs, and turns the snapshots into one verdict per assertion.

Three rules carried over from the keyboard wedge, because they are the same
failure modes:

1. **A check that could not see enough says `cantTell`.** A run cut short by
   the A9.3 budget, a focus step that did not land, a precondition the widget
   never reached — none of those are evidence of a defect.
2. **An assertion nobody implemented says `notChecked`, never `pass`.** Every
   assertion in a contract gets a result; a contract the runner has no checks
   for reports every line as unchecked rather than disappearing.
3. **`warning` assertions never gate.** A failed warning maps to
   `cantTell`/`NEEDS_REVIEW` when it becomes a Finding; only a failed
   `violation` is authoritative.

And one new one (A9.4): a contract must fail its own fail-fixture, or it is
rejected — see `verify_contract_fixtures`.

No model is involved anywhere in this file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Literal, Optional

from pydantic import BaseModel

from verity.agents.validator.severity import assign_severity
from verity.models.schemas import (
    Confidence,
    Evidence,
    ExerciseResult,
    Finding,
    InteractionSnapshot,
    InteractionStep,
    Level,
    Modality,
    Provenance,
    SuccessCriterion,
    Widget,
    WidgetInventory,
    WidgetNode,
)
from verity.rulepacks import ApgContract, Severity, load_contracts

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "data" / "fixtures"

AssertionOutcome = Literal["pass", "fail", "cantTell", "notChecked"]
Verdict = tuple[AssertionOutcome, str]


class AssertionResult(BaseModel):
    """One contract assertion, judged against one widget."""
    contract: str
    assertion_id: str
    severity: Severity
    wcag: Optional[str] = None
    section: Literal["structure", "keyboard"]
    widget: str
    outcome: AssertionOutcome
    detail: str
    trace: list[str] = []


class InteractionBudget(BaseModel):
    """
    A9.3 — how much interaction one page may cost.

    Per widget, the worker enforces the step and wall-clock caps and reports a
    truncated run as incomplete. Per page, `max_widgets` bounds the total: a
    page with 400 menu buttons is checked up to the cap and the rest are
    listed as skipped, never silently treated as clean.
    """
    max_widgets: int = 50
    max_steps_per_widget: int = 40
    max_ms_per_widget: int = 10_000


class ContractRun(BaseModel):
    """Everything the runner did on one page."""
    results: list[AssertionResult] = []
    # contract name -> how many widgets matched it
    widgets_matched: dict[str, int] = {}
    # widget selectors matched but not exercised because the page budget ran out
    widgets_skipped: list[str] = []
    shadow_roots_skipped: int = 0
    iframes_skipped: int = 0


# exercise(widget, steps, watch, budget) -> ExerciseResult. In production this
# is an RPC to `exerciseWidget` (see `rpc_exerciser`); in unit tests a fake.
Exerciser = Callable[[Widget, list[InteractionStep], list[str], InteractionBudget], Awaitable[ExerciseResult]]


# --- matching a widget to a contract (A9.1: "identify by ARIA role") --------

_MATCH_KEYS = {"role", "has", "lacks", "values"}


def matches(match: dict, widget: Widget) -> bool:
    """
    Does this widget fall under a contract's `match:` block?

    Supported keys: `role` (one role or a list), `has` / `lacks` (attribute
    names that must be present / absent), `values` (attribute -> allowed
    values). An unknown key is an error, not ignored: a typo'd `lack:` that
    silently matched everything would judge widgets against the wrong pattern.
    """
    unknown = set(match) - _MATCH_KEYS
    if unknown:
        raise ValueError(f"unknown contract match key(s): {sorted(unknown)}")
    if not match:
        return False
    root = widget.root
    roles = match.get("role")
    if roles is not None:
        roles = [roles] if isinstance(roles, str) else list(roles)
        if root.role not in roles:
            return False
    if any(a not in root.attributes for a in match.get("has", [])):
        return False
    if any(a in root.attributes for a in match.get("lacks", [])):
        return False
    for attr, allowed in (match.get("values") or {}).items():
        if root.attributes.get(attr) not in [str(v) for v in allowed]:
            return False
    return True


# --- snapshot helpers -------------------------------------------------------

def _ids(value: Optional[str]) -> list[str]:
    return value.split() if value else []


def _after(run: Optional[ExerciseResult], step: int) -> Optional[InteractionSnapshot]:
    """The snapshot taken after step `step` (-1 = before any), or None if it never happened."""
    if run is None:
        return None
    for s in run.snapshots:
        if s.step_index == step:
            return s
    return None


def _state(snap: Optional[InteractionSnapshot], selector: str) -> Optional[WidgetNode]:
    if snap is None:
        return None
    for n in snap.states:
        if n.selector == selector:
            return n
    return None


def _related_by_id(widget: Widget, element_id: str) -> Optional[WidgetNode]:
    for n in widget.related:
        if n.attributes.get("id") == element_id:
            return n
    return None


def _named(node: WidgetNode) -> bool:
    return bool(node.accessible_name and node.accessible_name.strip())


def _out_of_tab_order(node: WidgetNode) -> bool:
    return node.tabindex is not None and node.tabindex < 0


def _missing_snapshot(run: Optional[ExerciseResult]) -> str:
    if run is None:
        return "the widget could not be exercised"
    return f"the interaction stopped early ({run.incomplete_reason or 'unknown reason'})"


def _trace(steps: list[InteractionStep]) -> list[str]:
    return [f"focus {s.target}" if s.action == "focus" else f"press {s.key!r}" for s in steps]


# --- pattern checks ---------------------------------------------------------

@dataclass(frozen=True)
class PatternChecks:
    """
    The executable half of one contract.

    `plan` returns the steps to play on a widget (possibly none); `evaluate`
    returns verdicts keyed by assertion id. Ids must exist in the contract —
    a verdict for an id the contract does not have is drift between the YAML
    and this file, and is raised rather than dropped.
    """
    plan: Callable[[Widget], list[InteractionStep]]
    evaluate: Callable[[Widget, Optional[ExerciseResult]], dict[str, Verdict]]


def _press(key: str) -> InteractionStep:
    return InteractionStep(action="press", key=key)


def _focus(selector: str) -> InteractionStep:
    return InteractionStep(action="focus", target=selector)


# tablist ------------------------------------------------------------------

def _tab_keys(widget: Widget) -> tuple[str, str]:
    # Orientation defaults to horizontal when absent (tablist.yaml).
    if widget.root.attributes.get("aria-orientation") == "vertical":
        return "ArrowDown", "ArrowUp"
    return "ArrowRight", "ArrowLeft"


def _in_tab_sequence(tab: WidgetNode) -> bool:
    return not tab.disabled and not _out_of_tab_order(tab)


def _tab_roles(widget: Widget) -> tuple[WidgetNode, WidgetNode]:
    """(start tab for arrow probes, selected tab for the Tab-out probe)."""
    tabs = widget.items
    in_seq = [t for t in tabs if _in_tab_sequence(t)]
    start = in_seq[0] if in_seq else tabs[0]
    selected = next((t for t in tabs if t.attributes.get("aria-selected") == "true"), start)
    return start, selected


def _tablist_plan(widget: Widget) -> list[InteractionStep]:
    if not widget.items:
        return []
    nxt, prv = _tab_keys(widget)
    start, selected = _tab_roles(widget)
    return [
        _focus(selected.selector),  # 0
        _press("Tab"),              # 1  tab-moves-out-of-the-tablist
        _focus(start.selector),     # 2
        _press(nxt),                # 3  arrow-keys-move-between-tabs
        _press(prv),                # 4
        _press("End"),              # 5  home-end-keys
        _press("Home"),             # 6
        _press("End"),              # 7  arrow-wrapping-is-optional
        _press(nxt),                # 8
    ]


def _tablist_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    tabs = widget.items
    v: dict[str, Verdict] = {}
    v["tablist-owns-tabs"] = (
        "notChecked",
        "ownership is how the inventory finds tabs (DOM containment + aria-owns), "
        "so it cannot also be checked from the inventory",
    )
    if not tabs:
        v["tablist-has-at-least-one-tab"] = ("fail", "the tablist owns no role=tab elements")
        return v
    v["tablist-has-at-least-one-tab"] = ("pass", f"{len(tabs)} tab(s)")

    # Structure: controls, panels, names, selection.
    dangling = [t.selector for t in tabs if not _ids(t.attributes.get("aria-controls"))
                or any(_related_by_id(widget, i) is None for i in _ids(t.attributes.get("aria-controls")))]
    v["tab-controls-a-panel"] = (
        ("fail", f"no resolvable aria-controls on: {', '.join(dangling)}") if dangling
        else ("pass", "every tab's aria-controls resolves")
    )

    pairs = [(t, _related_by_id(widget, i)) for t in tabs for i in _ids(t.attributes.get("aria-controls"))]
    pairs = [(t, p) for t, p in pairs if p is not None]
    if not pairs:
        v["controlled-element-is-a-tabpanel"] = ("cantTell", "no controlled element could be resolved")
        v["tabpanel-is-labelled-by-its-tab"] = ("cantTell", "no controlled element could be resolved")
        v["non-selected-panels-hidden"] = ("cantTell", "no controlled element could be resolved")
    else:
        wrong = [p.selector for _, p in pairs if p.role != "tabpanel"]
        v["controlled-element-is-a-tabpanel"] = (
            ("fail", f"not role=tabpanel: {', '.join(wrong)}") if wrong
            else ("pass", "every controlled element is a tabpanel")
        )
        unlabelled = [p.selector for t, p in pairs
                      if not t.attributes.get("id") or t.attributes["id"] not in _ids(p.attributes.get("aria-labelledby"))]
        v["tabpanel-is-labelled-by-its-tab"] = (
            ("fail", f"not aria-labelledby its tab: {', '.join(unlabelled)}") if unlabelled
            else ("pass", "every panel is labelled by its tab")
        )
        shown = [p.selector for t, p in pairs if t.attributes.get("aria-selected") != "true" and not p.hidden]
        v["non-selected-panels-hidden"] = (
            ("fail", f"panel shown for an unselected tab: {', '.join(shown)}") if shown
            else ("pass", "only the selected tab's panel is shown")
        )

    nameless = [t.selector for t in tabs if not _named(t)]
    v["tab-has-accessible-name"] = (
        ("fail", f"no accessible name: {', '.join(nameless)}") if nameless else ("pass", "every tab is named")
    )
    selected_count = sum(1 for t in tabs if t.attributes.get("aria-selected") == "true")
    v["exactly-one-tab-selected"] = (
        ("pass", "exactly one tab has aria-selected=true") if selected_count == 1
        else ("fail", f"{selected_count} tabs have aria-selected=true")
    )

    # Keyboard, static half.
    in_seq = [t for t in tabs if _in_tab_sequence(t)]
    others_ok = all(t.tabindex == -1 for t in tabs if t not in in_seq[:1])
    v["roving-tabindex"] = (
        ("pass", "one tab in the Tab sequence, the rest tabindex=-1") if len(in_seq) == 1 and others_ok
        else ("fail", f"{len(in_seq)} tabs are in the Tab sequence; a tablist exposes exactly one")
    )
    positive = list(widget.positive_tabindex_descendants)
    if widget.root.tabindex is not None and widget.root.tabindex > 0:
        positive.append(widget.root.selector)
    v["no-positive-tabindex"] = (
        ("fail", f"positive tabindex on: {', '.join(positive)}") if positive
        else ("pass", "no positive tabindex inside the tablist")
    )
    v["focus-visible-on-tabs"] = (
        "notChecked",
        "measured by the tab-order traversal (A4.3 -> keyboard.py SC 2.4.7), not by the contract runner",
    )

    # Keyboard, driven half.
    sels = [t.selector for t in tabs]
    start, selected = _tab_roles(widget)
    i = sels.index(start.selector)

    s0, s1 = _after(run, 0), _after(run, 1)
    if s0 is None or s1 is None:
        v["tab-moves-out-of-the-tablist"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != selected.selector:
        v["tab-moves-out-of-the-tablist"] = ("cantTell", "focus did not land on the selected tab")
    elif s1.active in sels:
        v["tab-moves-out-of-the-tablist"] = ("fail", f"Tab from the selected tab moved to {s1.active}, still inside the tablist")
    else:
        v["tab-moves-out-of-the-tablist"] = ("pass", f"Tab moved focus out to {s1.active or 'the end of the page'}")

    s2, s3, s4 = _after(run, 2), _after(run, 3), _after(run, 4)
    if len(tabs) < 2:
        v["arrow-keys-move-between-tabs"] = ("cantTell", "only one tab; there is nowhere to move")
    elif i == len(tabs) - 1:
        v["arrow-keys-move-between-tabs"] = ("cantTell", "the start tab is the last; next could wrap or stop")
    elif s2 is None or s3 is None or s4 is None:
        v["arrow-keys-move-between-tabs"] = ("cantTell", _missing_snapshot(run))
    elif s2.active != start.selector:
        v["arrow-keys-move-between-tabs"] = ("cantTell", "focus did not land on the start tab")
    elif s3.active == sels[i + 1] and s4.active == sels[i]:
        v["arrow-keys-move-between-tabs"] = ("pass", "next/previous arrow moved focus to the adjacent tab and back")
    elif s3.active == start.selector or s3.active not in sels:
        v["arrow-keys-move-between-tabs"] = (
            "fail", f"the next-tab arrow key left focus on {s3.active or 'the page'}, not the next tab")
    elif s4.active not in sels or s4.active == s3.active:
        v["arrow-keys-move-between-tabs"] = (
            "fail", f"the previous-tab arrow key left focus on {s4.active or 'the page'}")
    else:
        v["arrow-keys-move-between-tabs"] = ("cantTell", "focus moved between tabs, but not to the adjacent one")

    s5, s6 = _after(run, 5), _after(run, 6)
    if s5 is None or s6 is None:
        v["home-end-keys"] = ("cantTell", _missing_snapshot(run))
    elif s5.active == sels[-1] and s6.active == sels[0]:
        v["home-end-keys"] = ("pass", "End -> last tab, Home -> first tab")
    else:
        v["home-end-keys"] = ("fail", f"End -> {s5.active}, Home -> {s6.active}")

    s7, s8 = _after(run, 7), _after(run, 8)
    if s7 is None or s8 is None:
        v["arrow-wrapping-is-optional"] = ("cantTell", _missing_snapshot(run))
    elif s7.active != sels[-1]:
        v["arrow-wrapping-is-optional"] = ("cantTell", "could not reach the last tab to test the end")
    elif s8.active in (sels[0], sels[-1]):
        v["arrow-wrapping-is-optional"] = ("pass", "at the last tab the next arrow wraps or stops")
    else:
        v["arrow-wrapping-is-optional"] = ("fail", f"at the last tab the next arrow moved focus to {s8.active}")
    return v


# disclosure ----------------------------------------------------------------

def _controlled(widget: Widget) -> Optional[WidgetNode]:
    ids = _ids(widget.root.attributes.get("aria-controls"))
    return _related_by_id(widget, ids[0]) if ids else None


def _disclosure_plan(widget: Widget) -> list[InteractionStep]:
    return [_focus(widget.root.selector), _press("Enter"), _press(" ")]


def _expanded(snap: Optional[InteractionSnapshot], widget: Widget) -> Optional[str]:
    node = _state(snap, widget.root.selector)
    return node.attributes.get("aria-expanded") if node else None


def _disclosure_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    root = widget.root
    v: dict[str, Verdict] = {}
    v["button-has-accessible-name"] = (
        ("pass", f"named {root.accessible_name!r}") if _named(root) else ("fail", "the button has no accessible name")
    )
    exp = root.attributes.get("aria-expanded")
    v["aria-expanded-is-boolean"] = (
        ("pass", f"aria-expanded={exp}") if exp in ("true", "false")
        else ("fail", f"aria-expanded={exp!r} is not 'true' or 'false'")
    )
    ids = _ids(root.attributes.get("aria-controls"))
    content = _controlled(widget)
    if not ids:
        v["controls-references-existing-element"] = ("pass", "no aria-controls (optional for a disclosure)")
    elif content is None:
        v["controls-references-existing-element"] = ("fail", f"aria-controls={ids[0]!r} references nothing")
    else:
        v["controls-references-existing-element"] = ("pass", f"aria-controls resolves to {content.selector}")

    if root.disabled:
        v["button-in-tab-sequence"] = ("cantTell", "the button is disabled")
    elif _out_of_tab_order(root):
        v["button-in-tab-sequence"] = ("fail", f"tabindex={root.tabindex} removes it from the Tab sequence")
    else:
        v["button-in-tab-sequence"] = ("pass", "reachable by Tab")

    s0, s1, s2 = _after(run, 0), _after(run, 1), _after(run, 2)

    if content is None:
        v["expanded-state-matches-visibility"] = ("cantTell", "no aria-controls target to compare against")
    else:
        mismatched = []
        for snap in (s for s in (_after(run, -1), s0, s1, s2) if s is not None):
            b, c = _state(snap, root.selector), _state(snap, content.selector)
            if b is None or c is None or b.attributes.get("aria-expanded") not in ("true", "false"):
                continue
            if (b.attributes["aria-expanded"] == "true") == c.hidden:
                mismatched.append(snap.step_index)
        v["expanded-state-matches-visibility"] = (
            ("fail", f"aria-expanded disagrees with the content's visibility after step(s) {mismatched}")
            if mismatched else ("pass", "aria-expanded tracks the content's visibility")
        )

    if s0 is None or s1 is None:
        v["enter-toggles"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != root.selector:
        v["enter-toggles"] = ("cantTell", "focus did not land on the button")
    elif _expanded(s0, widget) == _expanded(s1, widget):
        v["enter-toggles"] = ("fail", f"Enter left aria-expanded={_expanded(s1, widget)}")
    else:
        v["enter-toggles"] = ("pass", f"Enter: aria-expanded {_expanded(s0, widget)} -> {_expanded(s1, widget)}")

    if s1 is None or s2 is None:
        v["space-toggles"] = ("cantTell", _missing_snapshot(run))
    elif s1.active != root.selector:
        v["space-toggles"] = ("cantTell", "focus was no longer on the button before Space")
    elif _expanded(s1, widget) == _expanded(s2, widget):
        v["space-toggles"] = ("fail", f"Space left aria-expanded={_expanded(s2, widget)}")
    else:
        v["space-toggles"] = ("pass", f"Space: aria-expanded {_expanded(s1, widget)} -> {_expanded(s2, widget)}")

    if s0 is None or s1 is None or s2 is None:
        v["focus-stays-on-button"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != root.selector:
        v["focus-stays-on-button"] = ("cantTell", "focus did not land on the button")
    elif s1.active == root.selector and s2.active == root.selector:
        v["focus-stays-on-button"] = ("pass", "focus stayed on the button")
    else:
        v["focus-stays-on-button"] = ("fail", f"focus moved to {s1.active if s1.active != root.selector else s2.active}")
    return v


# menu button ---------------------------------------------------------------

def _menu_button_plan(widget: Widget) -> list[InteractionStep]:
    return [
        _focus(widget.root.selector),  # 0
        _press("Enter"),               # 1  enter-opens-menu, open-focuses-first-item
        _press("ArrowDown"),           # 2  arrow-down-moves-to-next-item
        _press("Escape"),              # 3  escape-closes-and-returns-focus
        _press(" "),                   # 4  space-opens-menu
        _press("Escape"),              # 5  leave it closed
    ]


def _menu_button_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    root, items = widget.root, widget.items
    v: dict[str, Verdict] = {}
    v["trigger-has-accessible-name"] = (
        ("pass", f"named {root.accessible_name!r}") if _named(root) else ("fail", "the menu button has no accessible name")
    )
    if root.disabled:
        v["trigger-in-tab-sequence"] = ("cantTell", "the button is disabled")
    elif _out_of_tab_order(root):
        v["trigger-in-tab-sequence"] = ("fail", f"tabindex={root.tabindex} removes it from the Tab sequence")
    else:
        v["trigger-in-tab-sequence"] = ("pass", "reachable by Tab")

    ids = _ids(root.attributes.get("aria-controls"))
    menu = _controlled(widget)
    if not ids:
        v["controls-a-menu"] = ("cantTell", "no aria-controls (optional); the menu cannot be located")
    elif menu is None:
        v["controls-a-menu"] = ("fail", f"aria-controls={ids[0]!r} references nothing")
    elif menu.role != "menu":
        v["controls-a-menu"] = ("fail", f"aria-controls target has role={menu.role!r}, not menu")
    else:
        v["controls-a-menu"] = ("pass", f"controls {menu.selector} (role=menu)")

    menu_checks = ["menu-items-have-names", "menu-hidden-initially", "enter-opens-menu",
                   "open-focuses-first-item", "expanded-true-when-open", "arrow-down-moves-to-next-item",
                   "escape-closes-and-returns-focus", "space-opens-menu", "items-use-managed-focus"]
    if menu is None or menu.role != "menu" or not items:
        why = "no menu with menuitems could be located from aria-controls"
        for a in menu_checks:
            v[a] = ("cantTell", why)
        return v

    nameless = [i.selector for i in items if not _named(i)]
    v["menu-items-have-names"] = (
        ("fail", f"no accessible name: {', '.join(nameless)}") if nameless else ("pass", "every menuitem is named")
    )
    v["menu-hidden-initially"] = (
        ("pass", "the menu is not displayed before interaction") if menu.hidden
        else ("fail", "the menu is displayed before any interaction")
    )
    unmanaged = [i.selector for i in items if i.tabindex != -1]
    v["items-use-managed-focus"] = (
        ("fail", f"menuitems without tabindex=-1: {', '.join(unmanaged)}") if unmanaged
        else ("pass", "every menuitem has tabindex=-1")
    )

    sels = [i.selector for i in items]

    def is_open(snap: Optional[InteractionSnapshot]) -> Optional[bool]:
        node = _state(snap, menu.selector)
        return None if node is None else not node.hidden

    s0, s1, s2, s3, s4 = (_after(run, k) for k in range(5))

    opened_by_enter = False
    if s0 is None or s1 is None:
        v["enter-opens-menu"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != root.selector or is_open(s0) is not False:
        v["enter-opens-menu"] = ("cantTell", "precondition not met: button focused with the menu closed")
    elif is_open(s1):
        v["enter-opens-menu"] = ("pass", "Enter displayed the menu")
        opened_by_enter = True
    else:
        v["enter-opens-menu"] = ("fail", "Enter did not display the menu")

    if not opened_by_enter:
        v["open-focuses-first-item"] = ("cantTell", "the menu was not opened by Enter")
    elif s1.active == sels[0]:
        v["open-focuses-first-item"] = ("pass", "focus moved to the first menuitem")
    else:
        v["open-focuses-first-item"] = ("fail", f"after opening, focus is on {s1.active or 'the page'}, not the first menuitem")

    open_snaps = [s for s in (s1, s2, s3, s4, _after(run, 5)) if s is not None and is_open(s)]
    if not open_snaps:
        v["expanded-true-when-open"] = ("cantTell", "the menu was never displayed")
    else:
        bad = [s.step_index for s in open_snaps
               if (_state(s, root.selector) or root).attributes.get("aria-expanded") != "true"]
        v["expanded-true-when-open"] = (
            ("fail", f"menu displayed without aria-expanded=true after step(s) {bad}") if bad
            else ("pass", "aria-expanded=true whenever the menu is displayed")
        )

    if len(items) < 2:
        v["arrow-down-moves-to-next-item"] = ("cantTell", "only one menuitem")
    elif s1 is None or s2 is None or s1.active != sels[0]:
        v["arrow-down-moves-to-next-item"] = ("cantTell", "precondition not met: first menuitem focused")
    elif s2.active == sels[1]:
        v["arrow-down-moves-to-next-item"] = ("pass", "ArrowDown moved to the second menuitem")
    elif s2.active not in sels or s2.active == sels[0]:
        v["arrow-down-moves-to-next-item"] = ("fail", f"ArrowDown left focus on {s2.active or 'the page'}")
    else:
        v["arrow-down-moves-to-next-item"] = ("cantTell", "focus moved within the menu, but not to the next item")

    if s2 is None or s3 is None or not is_open(s2) or s2.active not in sels:
        v["escape-closes-and-returns-focus"] = ("cantTell", "precondition not met: menu open with focus on a menuitem")
    elif not is_open(s3) and s3.active == root.selector:
        v["escape-closes-and-returns-focus"] = ("pass", "Escape closed the menu and returned focus to the button")
    else:
        v["escape-closes-and-returns-focus"] = (
            "fail", f"after Escape the menu is {'open' if is_open(s3) else 'closed'} and focus is on {s3.active or 'the page'}")

    if s3 is None or s4 is None or is_open(s3) is not False or s3.active != root.selector:
        v["space-opens-menu"] = ("cantTell", "precondition not met: button focused with the menu closed")
    elif is_open(s4):
        v["space-opens-menu"] = ("pass", "Space displayed the menu")
    else:
        v["space-opens-menu"] = ("fail", "Space did not display the menu")
    return v


CHECKS: dict[str, PatternChecks] = {
    "tablist": PatternChecks(_tablist_plan, _tablist_evaluate),
    "disclosure": PatternChecks(_disclosure_plan, _disclosure_evaluate),
    "menu-button": PatternChecks(_menu_button_plan, _menu_button_evaluate),
}


# --- the runner -------------------------------------------------------------

def _watch(widget: Widget) -> list[str]:
    seen: list[str] = []
    for n in (widget.root, *widget.items, *widget.related):
        if n.selector not in seen:
            seen.append(n.selector)
    return seen


async def run_contracts(
    inventory: WidgetInventory,
    exercise: Exerciser,
    contracts: Optional[dict[str, ApgContract]] = None,
    budget: Optional[InteractionBudget] = None,
) -> ContractRun:
    """
    A9.1 — judge every inventoried widget against every contract it matches.

    `exercise` plays steps on a widget; any exception from it is a run that
    did not happen (every driven check then says cantTell), not a crash.
    """
    contracts = contracts if contracts is not None else load_contracts()
    budget = budget or InteractionBudget()
    out = ContractRun(
        shadow_roots_skipped=inventory.shadow_roots_skipped,
        iframes_skipped=inventory.iframes_skipped,
        widgets_matched={name: 0 for name in contracts},
    )
    exercised = 0

    for widget in inventory.widgets:
        for contract in contracts.values():
            if not matches(contract.match, widget):
                continue
            out.widgets_matched[contract.contract] += 1
            if exercised >= budget.max_widgets:
                out.widgets_skipped.append(widget.root.selector)
                continue
            exercised += 1

            checks = CHECKS.get(contract.contract)
            steps = checks.plan(widget) if checks else []
            run: Optional[ExerciseResult] = None
            if steps:
                try:
                    run = await exercise(widget, steps, _watch(widget), budget)
                except Exception as exc:
                    logger.info(
                        "exerciseWidget unavailable for %s (%s); driven checks are cantTell.",
                        widget.root.selector,
                        exc.__class__.__name__,
                    )
            verdicts = checks.evaluate(widget, run) if checks else {}

            sections = {a.id: (sec, a) for sec in ("structure", "keyboard")
                        for a in getattr(contract, sec)}
            stray = sorted(set(verdicts) - set(sections))
            if stray:
                raise ValueError(
                    f"checks for '{contract.contract}' returned verdicts for assertion ids the "
                    f"contract does not define: {stray}"
                )
            for aid, (section, assertion) in sections.items():
                outcome, detail = verdicts.get(
                    aid,
                    ("notChecked", "no check is implemented for this assertion" if checks
                     else "no checks are implemented for this contract"),
                )
                out.results.append(AssertionResult(
                    contract=contract.contract,
                    assertion_id=aid,
                    severity=assertion.severity,
                    wcag=assertion.wcag,
                    section=section,
                    widget=widget.root.selector,
                    outcome=outcome,
                    detail=detail,
                    trace=_trace(steps) if section == "keyboard" else [],
                ))
    return out


def rpc_exerciser(rpc_call: Callable[..., Awaitable[dict]], artifact_id: str) -> Exerciser:
    """Adapt the worker's `exerciseWidget` RPC to the runner's exercise callable."""
    async def exercise(
        widget: Widget, steps: list[InteractionStep], watch: list[str], budget: InteractionBudget
    ) -> ExerciseResult:
        raw = await rpc_call(
            "exerciseWidget",
            {
                "artifactId": artifact_id,
                "steps": [s.model_dump(exclude_none=True) for s in steps],
                "watch": watch,
                "maxSteps": budget.max_steps_per_widget,
                "maxMs": budget.max_ms_per_widget,
            },
        )
        return ExerciseResult.model_validate(raw)
    return exercise


async def run_contracts_on_artifact(
    rpc_call: Callable[..., Awaitable[dict]],
    artifact_id: str,
    contracts: Optional[dict[str, ApgContract]] = None,
    budget: Optional[InteractionBudget] = None,
) -> ContractRun:
    """
    Inventory a rendered page and run the contracts on it.

    This MUTATES the live page (it presses keys), so it belongs after
    everything that needs the rendered state — axe, contrast sampling, and the
    tab-order traversal — and before `releaseArtifact`.
    """
    inventory = WidgetInventory.model_validate(
        await rpc_call("inventoryWidgets", {"artifactId": artifact_id})
    )
    return await run_contracts(inventory, rpc_exerciser(rpc_call, artifact_id), contracts, budget)


# --- mapping to Findings ----------------------------------------------------

_CRITERIA: dict[str, tuple[str, Level]] = {
    "2.1.1": ("Keyboard", Level.A),
    "2.1.2": ("No Keyboard Trap", Level.A),
    "2.4.3": ("Focus Order", Level.A),
    "2.4.7": ("Focus Visible", Level.AA),
    "4.1.2": ("Name, Role, Value", Level.A),
}
# When an assertion does not pin its own SC (several of tablist.yaml's do
# not), structure is about name/role/value and keyboard is about operability.
_DEFAULT_SC = {"structure": "4.1.2", "keyboard": "2.1.1"}


def to_findings(run: ContractRun, page_state_hash: str) -> list[Finding]:
    """
    Turn assertion results into Findings.

    | result                 | outcome  | provenance    |
    |------------------------|----------|---------------|
    | violation, fail        | fail     | AUTHORITATIVE |
    | violation/warning, pass| pass     | AUTHORITATIVE |
    | warning, fail          | cantTell | NEEDS_REVIEW  |
    | cantTell               | cantTell | NEEDS_REVIEW  |
    | notChecked             | (none)   |               |

    A failed warning is a "suspicious, but legitimate variants exist" — it is
    reported for review and can never fail a build.
    """
    from verity.orchestrator.main import derive_finding_id

    findings: list[Finding] = []
    for r in run.results:
        if r.outcome == "notChecked":
            continue
        decided = r.outcome == "pass" or (r.outcome == "fail" and r.severity is Severity.VIOLATION)
        outcome = r.outcome if decided else "cantTell"
        provenance = Provenance.AUTHORITATIVE if decided else Provenance.NEEDS_REVIEW
        sc_id = r.wcag if r.wcag in _CRITERIA else _DEFAULT_SC[r.section]
        name, level = _CRITERIA[sc_id]
        rule_id = f"apg-{r.contract}-{r.assertion_id}"
        findings.append(Finding(
            id=derive_finding_id(rule_id, r.widget),
            rule_id=rule_id,
            sc=SuccessCriterion(id=sc_id, name=name, level=level, modality=Modality.INTERACTION),
            provenance=provenance,
            severity=assign_severity(
                sc_id=sc_id, level=level, outcome=outcome, provenance=provenance, engine_impact=None,
            ),
            confidence=Confidence(
                score=1.0 if decided else 0.0,
                method="apg-contract" if decided else "apg-contract-indeterminate",
                model=None,
                escape_used=False,
            ),
            agent="interaction",
            engine="node-worker",
            outcome=outcome,
            message=f"[{r.contract}] {r.assertion_id}: {r.detail}",
            evidence=Evidence(
                dom_selector=r.widget,
                interaction_trace=r.trace or None,
                computed_values={
                    "apg_contract": r.contract,
                    "assertion": r.assertion_id,
                    "assertion_severity": r.severity.value,
                    "assertion_outcome": r.outcome,
                },
            ),
            page_state_hash=page_state_hash,
        ))
    return findings


# --- A9.4: the contract-fixture gate ----------------------------------------

async def verify_contract_fixtures(
    run_fixture: Callable[[Path], Awaitable[ContractRun]],
    contracts: Optional[dict[str, ApgContract]] = None,
) -> list[str]:
    """
    Every contract must ship a passing and a failing fixture, and behave on both.

    Returns a list of problems; empty means the gate passes. Rejects a
    contract when:

    - it declares no fixtures, or a fixture file is missing;
    - a fixture contains no widget the contract matches (a gate that matched
      nothing proves nothing);
    - on its pass fixture, any assertion fails, or any implemented
      `violation` is only `cantTell` (a check that cannot decide on a
      textbook widget is not working);
    - on its fail fixture, no `violation` fails — **a contract that cannot
      fail its own fail-fixture checks nothing.**
    """
    contracts = contracts if contracts is not None else load_contracts()
    problems: list[str] = []
    for name, contract in sorted(contracts.items()):
        if contract.fixtures is None:
            problems.append(f"{name}: declares no fixtures (A9.4 requires a pass and a fail fixture)")
            continue
        paths = {"pass": FIXTURES_DIR / contract.fixtures.pass_, "fail": FIXTURES_DIR / contract.fixtures.fail}
        missing = [f"{k}={p}" for k, p in paths.items() if not p.exists()]
        if missing:
            problems.append(f"{name}: fixture file(s) missing: {', '.join(missing)}")
            continue

        for kind, path in paths.items():
            run = await run_fixture(path)
            if run.widgets_matched.get(name, 0) == 0:
                problems.append(f"{name}: {kind} fixture {path.name} contains no widget matching the contract")
                continue
            mine = [r for r in run.results if r.contract == name]
            if kind == "pass":
                for r in mine:
                    if r.outcome == "fail":
                        problems.append(f"{name}: false alarm on pass fixture — {r.assertion_id}: {r.detail}")
                    elif r.outcome == "cantTell" and r.severity is Severity.VIOLATION:
                        problems.append(f"{name}: undecided on pass fixture — {r.assertion_id}: {r.detail}")
            elif not any(r.outcome == "fail" and r.severity is Severity.VIOLATION for r in mine):
                problems.append(f"{name}: fail fixture {path.name} fails no violation — the contract checks nothing")
    return problems
