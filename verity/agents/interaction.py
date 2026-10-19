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
import time
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
# (outcome, detail), or (outcome, detail, APG_ONLY) for a failure that breaks
# the APG pattern but is not a WCAG barrier — e.g. every tab in a tablist is
# in the Tab order (no roving tabindex): un-idiomatic, but every tab is still
# reachable. Such a result is reported at `warning` severity whatever the
# contract says, so it is reviewed and never gates. Verity is a WCAG
# conformance engine; APG is how we know what to test, not the bar we gate on.
Verdict = tuple
APG_ONLY = "apg-only"


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
    # Worst case is every step inert, each waiting out the worker's effect
    # window (~1.2 s) — a tablist probe is 9 steps.
    max_ms_per_widget: int = 20_000
    # The whole page. Widgets left when it runs out are listed in
    # `widgets_skipped`, exactly like those beyond `max_widgets`.
    max_ms_per_page: int = 120_000


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


def _tab_sequence_verdict(widget: Widget) -> Verdict:
    """
    Is a trigger button reachable from the keyboard at all?

    tabindex=-1 inside a roving-tabindex widget (APG "tabs with action
    buttons") is reached with the arrow keys by design — the ARROW_NAVIGABLE
    rule from the traversal. We did not drive those arrows, so it is cantTell,
    never a fail.
    """
    root = widget.root
    if root.disabled:
        return ("cantTell", "the button is disabled")
    if _out_of_tab_order(root) and widget.roving_ancestor:
        return ("cantTell", f"tabindex={root.tabindex} inside roving-tabindex widget "
                            f"{widget.roving_ancestor}; reached by arrow keys by design")
    if _out_of_tab_order(root):
        # Same rule as the traversal's UNKNOWN: tabindex=-1 outside a known
        # roving pattern may still be reached by a key route the page provides.
        # Whether it is reachable at all is what the tab-order traversal
        # measures (SC 2.1.1); asserting it here from the attribute alone was
        # a false alarm on stripe.com's navigation.
        return ("cantTell", f"tabindex={root.tabindex} takes it out of the Tab sequence; "
                            "reachability is judged by the tab-order traversal")
    return ("pass", "reachable by Tab")


def _missing_snapshot(run: Optional[ExerciseResult]) -> str:
    if run is None:
        return "the widget could not be exercised"
    return f"the interaction stopped early ({run.incomplete_reason or 'unknown reason'})"


def _trace(steps: list[InteractionStep]) -> list[str]:
    return [f"press {s.key!r}" if s.action == "press" else f"{s.action} {s.target}" for s in steps]


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
    # Extra selectors to snapshot beyond the widget's own nodes (Week 9,
    # Track B): a popup that only exists once opened (`[id="lb"]`), or
    # `#dlg:focus-within`, whose presence in `missing` says focus left it.
    watch: Optional[Callable[[Widget], list[str]]] = None


def _press(key: str) -> InteractionStep:
    return InteractionStep(action="press", key=key)


def _move(key: str) -> InteractionStep:
    """A key whose effect is moving focus (arrows, Home/End, Tab)."""
    return InteractionStep(action="press", key=key, expect="focus")


def _focus(selector: str) -> InteractionStep:
    return InteractionStep(action="focus", target=selector)


def _click(selector: str) -> InteractionStep:
    return InteractionStep(action="click", target=selector)


def _key_parity(key: str, key_worked: bool, other_key: str, other_worked: bool,
                click_worked: Optional[bool], effect: str) -> Verdict:
    """
    WCAG 2.1.1 asks whether the widget can be operated from the keyboard — not
    whether every APG key works. So a key that does nothing is:

    - a barrier (fail) only when the OTHER key fails too and a mouse click
      does have the effect: the keyboard user is locked out of something a
      mouse user can do;
    - an APG deviation (fail, APG_ONLY) when the other key works;
    - undecided when a click has no effect either — an accordion that keeps
      one panel open behaves the same for mouse and keyboard (github.com).
    """
    if key_worked:
        return ("pass", f"{key} can {effect}")
    if other_worked:
        return ("fail", f"{key} cannot {effect}, but {other_key} can", APG_ONLY)
    if click_worked is None:
        return ("cantTell", f"neither {key} nor {other_key} can {effect}, and a click could not be compared")
    if click_worked:
        return ("fail", f"a click can {effect}, but neither {key} nor {other_key} can")
    return ("cantTell", f"neither {key}, {other_key} nor a click can {effect} — not a keyboard-only difference")


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
        _move("Tab"),               # 1  tab-moves-out-of-the-tablist
        _focus(start.selector),     # 2
        _move(nxt),                 # 3  arrow-keys-move-between-tabs
        _move(prv),                 # 4
        _move("End"),               # 5  home-end-keys
        _move("Home"),              # 6
        _move("End"),               # 7  arrow-wrapping-is-optional
        _move(nxt),                 # 8
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
    # Missing/dangling aria-controls is an APG authoring error with patchy AT
    # support — reported, never a WCAG barrier on its own.
    v["tab-controls-a-panel"] = (
        ("fail", f"no resolvable aria-controls on: {', '.join(dangling)}", APG_ONLY) if dangling
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
    if len(in_seq) == 1 and others_ok:
        v["roving-tabindex"] = ("pass", "one tab in the Tab sequence, the rest tabindex=-1")
    elif not in_seq:
        v["roving-tabindex"] = ("fail", "no tab is in the Tab sequence; the tablist cannot be reached by Tab")
    else:
        # Every tab still reachable by Tab: not idiomatic, not a barrier.
        v["roving-tabindex"] = (
            "fail", f"{len(in_seq)} tabs are in the Tab sequence; a tablist exposes exactly one", APG_ONLY)
    arrows_required = any(t.tabindex == -1 for t in tabs)
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
    elif s1.active == selected.selector:
        v["tab-moves-out-of-the-tablist"] = ("fail", "Tab did not move focus off the selected tab")
    elif s1.active in sels:
        # Focus kept moving — onto the next tab. Not a trap; un-idiomatic.
        v["tab-moves-out-of-the-tablist"] = (
            "fail", f"Tab from the selected tab moved to {s1.active}, still inside the tablist", APG_ONLY)
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
        # A barrier only when arrows are the sole route to the other tabs.
        v["arrow-keys-move-between-tabs"] = (
            "fail", f"the next-tab arrow key left focus on {s3.active or 'the page'}, not the next tab",
            *(() if arrows_required else (APG_ONLY,)))
    elif s4.active not in sels or s4.active == s3.active:
        v["arrow-keys-move-between-tabs"] = (
            "fail", f"the previous-tab arrow key left focus on {s4.active or 'the page'}",
            *(() if arrows_required else (APG_ONLY,)))
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
    root = widget.root.selector
    # 3: a click, for keyboard parity (see _key_parity).
    return [_focus(root), _press("Enter"), _press(" "), _click(root)]


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

    v["button-in-tab-sequence"] = _tab_sequence_verdict(widget)

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

    s3 = _after(run, 3)
    enter_flips = (s0 is not None and s1 is not None and s0.active == root.selector
                   and _expanded(s0, widget) != _expanded(s1, widget))
    space_flips = (s1 is not None and s2 is not None and s1.active == root.selector
                   and _expanded(s1, widget) != _expanded(s2, widget))
    click_flips = None if s3 is None or s2 is None else _expanded(s2, widget) != _expanded(s3, widget)

    if s0 is None or s1 is None:
        v["enter-toggles"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != root.selector:
        v["enter-toggles"] = ("cantTell", "focus did not land on the button")
    else:
        v["enter-toggles"] = _key_parity("Enter", enter_flips, "Space", space_flips, click_flips,
                                         "toggle aria-expanded")

    if s1 is None or s2 is None:
        v["space-toggles"] = ("cantTell", _missing_snapshot(run))
    elif s1.active != root.selector:
        v["space-toggles"] = ("cantTell", "focus was no longer on the button before Space")
    else:
        v["space-toggles"] = _key_parity("Space", space_flips, "Enter", enter_flips, click_flips,
                                         "toggle aria-expanded")

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
        _move("ArrowDown"),            # 2  arrow-down-moves-to-next-item
        _press("Escape"),              # 3  escape-closes-and-returns-focus
        _press(" "),                   # 4  space-opens-menu
        _press("Escape"),              # 5  leave it closed
        _click(widget.root.selector),  # 6  keyboard parity: does a click open it?
        _press("Escape"),              # 7  and close again
    ]


def _menu_button_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    root, items = widget.root, widget.items
    v: dict[str, Verdict] = {}
    v["trigger-has-accessible-name"] = (
        ("pass", f"named {root.accessible_name!r}") if _named(root) else ("fail", "the menu button has no accessible name")
    )
    v["trigger-in-tab-sequence"] = _tab_sequence_verdict(widget)

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

    sels = [i.selector for i in items]

    def is_open(snap: Optional[InteractionSnapshot]) -> Optional[bool]:
        node = _state(snap, menu.selector)
        return None if node is None else not node.hidden

    ids_to_items = {i.attributes["id"]: i.selector for i in items if i.attributes.get("id")}

    def focused_item(snap: Optional[InteractionSnapshot]) -> Optional[str]:
        """
        The menuitem the user is on: DOM focus on an item, or DOM focus on the
        menu with aria-activedescendant naming an item. The APG documents both
        (the "actions" and "actions-active-descendant" examples); judging only
        DOM focus would fail the second, correct one.
        """
        if snap is None:
            return None
        if snap.active in sels:
            return snap.active
        if snap.active == menu.selector:
            m = _state(snap, menu.selector)
            return ids_to_items.get((m.attributes.get("aria-activedescendant") or "") if m else "")
        return None

    s0, s1, s2, s3, s4 = (_after(run, k) for k in range(5))

    unmanaged = [i.selector for i in items if i.tabindex != -1]
    uses_activedescendant = any(
        s is not None and s.active == menu.selector and focused_item(s) is not None for s in (s1, s2)
    )
    if not unmanaged:
        v["items-use-managed-focus"] = ("pass", "every menuitem has tabindex=-1")
    elif uses_activedescendant:
        v["items-use-managed-focus"] = ("pass", "focus is managed with aria-activedescendant")
    else:
        v["items-use-managed-focus"] = ("fail", f"menuitems without tabindex=-1: {', '.join(unmanaged)}")

    s5, s6 = _after(run, 5), _after(run, 6)
    space_ready = s3 is not None and s4 is not None and is_open(s3) is False and s3.active == root.selector
    space_opens = space_ready and bool(is_open(s4))
    click_opens = None if s5 is None or s6 is None or is_open(s5) is not False else bool(is_open(s6))
    # Items only reachable through the menu's own key handling (tabindex=-1):
    # then focus not moving into the menu, or ArrowDown not moving, locks the
    # keyboard user out. Otherwise Tab still gets there — an APG deviation.
    keys_required = () if all(i.tabindex == -1 for i in items) else (APG_ONLY,)

    opened_by_enter = False
    if s0 is None or s1 is None:
        v["enter-opens-menu"] = ("cantTell", _missing_snapshot(run))
    elif s0.active != root.selector or is_open(s0) is not False:
        v["enter-opens-menu"] = ("cantTell", "precondition not met: button focused with the menu closed")
    else:
        opened_by_enter = bool(is_open(s1))
        v["enter-opens-menu"] = _key_parity("Enter", opened_by_enter, "Space", space_opens, click_opens,
                                            "open the menu")

    if not opened_by_enter:
        v["open-focuses-first-item"] = ("cantTell", "the menu was not opened by Enter")
    elif focused_item(s1) == sels[0]:
        v["open-focuses-first-item"] = ("pass", "focus moved to the first menuitem")
    else:
        v["open-focuses-first-item"] = (
            "fail", f"after opening, focus is on {s1.active or 'the page'}, not the first menuitem",
            *keys_required)

    open_snaps = [s for s in (s1, s2, s3, s4, s5, s6) if s is not None and is_open(s)]
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
    elif s1 is None or s2 is None or focused_item(s1) != sels[0]:
        v["arrow-down-moves-to-next-item"] = ("cantTell", "precondition not met: first menuitem focused")
    elif focused_item(s2) == sels[1]:
        v["arrow-down-moves-to-next-item"] = ("pass", "ArrowDown moved to the second menuitem")
    elif focused_item(s2) in (None, sels[0]):
        v["arrow-down-moves-to-next-item"] = (
            "fail", f"ArrowDown left focus on {focused_item(s2) or s2.active or 'the page'}", *keys_required)
    else:
        v["arrow-down-moves-to-next-item"] = ("cantTell", "focus moved within the menu, but not to the next item")

    if s2 is None or s3 is None or not is_open(s2) or focused_item(s2) is None:
        v["escape-closes-and-returns-focus"] = ("cantTell", "precondition not met: menu open with focus on a menuitem")
    elif not is_open(s3) and s3.active == root.selector:
        v["escape-closes-and-returns-focus"] = ("pass", "Escape closed the menu and returned focus to the button")
    else:
        v["escape-closes-and-returns-focus"] = (
            "fail", f"after Escape the menu is {'open' if is_open(s3) else 'closed'} and focus is on {s3.active or 'the page'}")

    if not space_ready:
        v["space-opens-menu"] = ("cantTell", "precondition not met: button focused with the menu closed")
    else:
        v["space-opens-menu"] = _key_parity("Space", space_opens, "Enter", opened_by_enter, click_opens,
                                            "open the menu")
    return v


# dialog (Track B, Week 9) ---------------------------------------------------
#
# Matched on the trigger (aria-haspopup="dialog"), because a closed dialog is
# not rendered and only the author's declaration says which button opens it.
# See data/apg-contracts/dialog.yaml for why each check is what it is.

_DIALOG_ROLES = ("dialog", "alertdialog")


def _is_dialog(node: Optional[WidgetNode]) -> bool:
    return node is not None and (node.role in _DIALOG_ROLES or node.tag == "dialog")


def _focus_within(selector: str) -> str:
    return f"{selector}:focus-within"


def _dialog_watch(widget: Widget) -> list[str]:
    d = _controlled(widget)
    return [_focus_within(d.selector)] if _is_dialog(d) else []


def _dialog_plan(widget: Widget) -> list[InteractionStep]:
    if not _is_dialog(_controlled(widget)):
        return []
    root = widget.root.selector
    return [
        _focus(root),         # 0
        _press("Enter"),      # 1  enter-opens-dialog, focus-moves-into-dialog
        _move("Tab"),         # 2  tab-stays-in-modal-dialog
        _move("Tab"),         # 3
        _move("Tab"),         # 4
        _move("Shift+Tab"),   # 5
        _press("Escape"),     # 6  escape-closes-dialog, focus-returns-to-trigger
        _focus(root),         # 7
        _press(" "),          # 8  space-opens-dialog
        _press("Escape"),     # 9
        _click(root),         # 10 keyboard parity: does a click open it?
        _press("Escape"),     # 11
    ]


def _dialog_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    root = widget.root
    v: dict[str, Verdict] = {}
    v["trigger-has-accessible-name"] = (
        ("pass", f"named {root.accessible_name!r}") if _named(root)
        else ("fail", "the dialog trigger has no accessible name")
    )
    v["trigger-in-tab-sequence"] = _tab_sequence_verdict(widget)

    ids = _ids(root.attributes.get("aria-controls"))
    dialog = _controlled(widget)
    if not ids:
        v["controls-a-dialog"] = ("cantTell", "no aria-controls; the dialog cannot be located")
    elif dialog is None:
        v["controls-a-dialog"] = ("fail", f"aria-controls={ids[0]!r} references nothing")
    elif not _is_dialog(dialog):
        v["controls-a-dialog"] = ("fail", f"aria-controls target is <{dialog.tag}> role={dialog.role!r}, not a dialog")
    else:
        v["controls-a-dialog"] = ("pass", f"controls {dialog.selector}")

    dependent = ["dialog-has-accessible-name", "dialog-hidden-initially", "enter-opens-dialog",
                 "space-opens-dialog", "focus-moves-into-dialog", "tab-stays-in-modal-dialog",
                 "escape-closes-dialog", "focus-returns-to-trigger"]
    if not _is_dialog(dialog):
        for a in dependent:
            v[a] = ("cantTell", "no dialog could be located from aria-controls")
        return v
    assert dialog is not None

    if (dialog.attributes.get("aria-label") or "").strip():
        v["dialog-has-accessible-name"] = ("pass", "named by aria-label")
    elif _ids(dialog.attributes.get("aria-labelledby")) and _named(dialog):
        v["dialog-has-accessible-name"] = ("pass", f"named by aria-labelledby: {dialog.accessible_name!r}")
    else:
        v["dialog-has-accessible-name"] = ("fail", "the dialog has neither aria-label nor a resolvable aria-labelledby")
    v["dialog-hidden-initially"] = (
        ("pass", "the dialog is not displayed before interaction") if dialog.hidden
        else ("fail", "the dialog is displayed before any interaction")
    )

    fw = _focus_within(dialog.selector)

    def is_open(snap: Optional[InteractionSnapshot]) -> Optional[bool]:
        node = _state(snap, dialog.selector)
        return None if node is None else not node.hidden

    def inside(snap: Optional[InteractionSnapshot]) -> bool:
        return snap is not None and fw not in snap.missing

    s = {k: _after(run, k) for k in range(-1, 12)}

    enter_ready = (s[0] is not None and s[1] is not None
                   and s[0].active == root.selector and is_open(s[0]) is False)
    enter_opens = enter_ready and bool(is_open(s[1]))
    space_ready = (s[7] is not None and s[8] is not None
                   and s[7].active == root.selector and is_open(s[7]) is False)
    space_opens = space_ready and bool(is_open(s[8]))
    click_opens: Optional[bool] = (
        None if s[9] is None or s[10] is None or is_open(s[9]) is not False else bool(is_open(s[10]))
    )

    if s[0] is None or s[1] is None:
        v["enter-opens-dialog"] = ("cantTell", _missing_snapshot(run))
    elif not enter_ready:
        v["enter-opens-dialog"] = ("cantTell", "precondition not met: trigger focused with the dialog closed")
    else:
        # The other key only counts as evidence if its own precondition held.
        v["enter-opens-dialog"] = _key_parity("Enter", enter_opens, "Space", space_opens,
                                              click_opens if space_ready else None, "open the dialog")

    if s[7] is None or s[8] is None:
        v["space-opens-dialog"] = ("cantTell", _missing_snapshot(run))
    elif not space_ready:
        v["space-opens-dialog"] = ("cantTell", "precondition not met: trigger focused with the dialog closed")
    else:
        v["space-opens-dialog"] = _key_parity("Space", space_opens, "Enter", enter_opens,
                                              click_opens if enter_ready else None, "open the dialog")

    opened = s[1] if enter_opens else s[8] if space_opens else None
    if opened is None:
        v["focus-moves-into-dialog"] = ("cantTell", "the keyboard never opened the dialog")
    elif inside(opened):
        v["focus-moves-into-dialog"] = ("pass", f"focus moved into the dialog ({opened.active})")
    elif opened.active is None:
        v["focus-moves-into-dialog"] = ("cantTell", "after opening, focus is on no element (the page body)")
    else:
        v["focus-moves-into-dialog"] = (
            "fail", f"the dialog opened but focus stayed outside it, on {opened.active}")

    modal = dialog.attributes.get("aria-modal") == "true"
    if not (enter_opens and inside(s[1])):
        v["tab-stays-in-modal-dialog"] = ("cantTell", "precondition not met: Enter opened the dialog with focus inside")
    elif not modal:
        v["tab-stays-in-modal-dialog"] = ("cantTell", "the dialog does not declare aria-modal=\"true\"; "
                                                      "a non-modal dialog may let Tab leave")
    else:
        escaped: list[str] = []
        verdict: Optional[Verdict] = None
        for k in (2, 3, 4, 5):
            snap = s[k]
            if snap is None:
                verdict = ("cantTell", _missing_snapshot(run))
                break
            if not is_open(snap):
                verdict = ("cantTell", f"the dialog closed after step {k}; containment could not be judged")
                break
            # active None = the browser's own UI, not the obscured page.
            if snap.active is not None and not inside(snap):
                escaped.append(f"step {k} -> {snap.active}")
        if escaped:
            v["tab-stays-in-modal-dialog"] = ("fail", f"Tab moved focus out of the modal dialog: {'; '.join(escaped)}")
        elif verdict is not None:
            v["tab-stays-in-modal-dialog"] = verdict
        else:
            v["tab-stays-in-modal-dialog"] = ("pass", "Tab and Shift+Tab stayed inside the dialog")

    if s[5] is None or s[6] is None:
        v["escape-closes-dialog"] = ("cantTell", _missing_snapshot(run))
        v["focus-returns-to-trigger"] = ("cantTell", _missing_snapshot(run))
    elif not (is_open(s[5]) and inside(s[5])):
        why = "precondition not met: dialog open with focus inside before Escape"
        v["escape-closes-dialog"] = ("cantTell", why)
        v["focus-returns-to-trigger"] = ("cantTell", why)
    elif is_open(s[6]) is not False:
        v["escape-closes-dialog"] = ("fail", "Escape did not hide the dialog")
        v["focus-returns-to-trigger"] = ("cantTell", "Escape did not close the dialog")
    else:
        v["escape-closes-dialog"] = ("pass", "Escape hid the dialog")
        v["focus-returns-to-trigger"] = (
            ("pass", "focus returned to the trigger") if s[6].active == root.selector
            else ("fail", f"after closing, focus is on {s[6].active or 'the page'}, not the trigger")
        )
    return v


# combobox (Track B, Week 9) -------------------------------------------------
#
# DOM focus stays on the combobox; arrows move a virtual focus announced via
# aria-activedescendant. See data/apg-contracts/combobox.yaml.

_POPUP_ROLES = ("listbox", "grid", "tree", "dialog")


def _popup_id(widget: Widget) -> Optional[str]:
    ids = _ids(widget.root.attributes.get("aria-controls")) or _ids(widget.root.attributes.get("aria-owns"))
    return ids[0] if ids else None


def _node_by_id(snap: Optional[InteractionSnapshot], element_id: str) -> Optional[WidgetNode]:
    if snap is None:
        return None
    for n in snap.states:
        if n.attributes.get("id") == element_id:
            return n
    return None


def _combobox_watch(widget: Widget) -> list[str]:
    # The popup may not exist at inventory time (rendered on open), so watch
    # it by id rather than by an inventory selector.
    pid = _popup_id(widget)
    return [f'[id="{pid}"]'] if pid and '"' not in pid and "\\" not in pid else []


def _combobox_plan(widget: Widget) -> list[InteractionStep]:
    root = widget.root.selector
    return [
        _focus(root),              # 0
        _press("ArrowDown"),       # 1  keyboard-opens-popup, arrow-keys-reach-options
        _press("ArrowDown"),       # 2
        _press("Escape"),          # 3  escape-closes-popup
        _focus(root),              # 4
        _press("Alt+ArrowDown"),   # 5  keyboard-opens-popup (alternative key)
        _press("Escape"),          # 6
        _click(root),              # 7  keyboard parity: does a click open it?
        _press("Escape"),          # 8
    ]


def _combobox_evaluate(widget: Widget, run: Optional[ExerciseResult]) -> dict[str, Verdict]:
    root, options = widget.root, widget.items
    v: dict[str, Verdict] = {}
    v["combobox-has-accessible-name"] = (
        ("pass", f"named {root.accessible_name!r}") if _named(root)
        else ("fail", "the combobox has no accessible name")
    )
    exp = root.attributes.get("aria-expanded")
    if exp in ("true", "false"):
        v["aria-expanded-is-boolean"] = ("pass", f"aria-expanded={exp}")
    elif exp is None:
        v["aria-expanded-is-boolean"] = (
            "fail", "aria-expanded is absent (ARIA 1.2 requires it on combobox; default false)", APG_ONLY)
    else:
        v["aria-expanded-is-boolean"] = ("fail", f"aria-expanded={exp!r} is not 'true' or 'false'")

    if not options:
        v["options-have-names"] = ("cantTell", "no options in the DOM at scan time")
    else:
        nameless = [o.selector for o in options if not _named(o)]
        v["options-have-names"] = (
            ("fail", f"no accessible name: {', '.join(nameless)}") if nameless else ("pass", "every option is named")
        )

    pid = _popup_id(widget)
    at_load = _related_by_id(widget, pid) if pid else None
    if pid is None:
        v["popup-hidden-initially"] = ("cantTell", "no aria-controls or aria-owns; the popup cannot be located")
    elif at_load is None or at_load.hidden:
        v["popup-hidden-initially"] = ("pass", "the popup is not displayed before interaction")
    else:
        v["popup-hidden-initially"] = ("fail", "the popup is displayed before any interaction")

    def is_open(snap: Optional[InteractionSnapshot]) -> Optional[bool]:
        if snap is None or pid is None or not snap.states:
            return None
        node = _node_by_id(snap, pid)
        return False if node is None else not node.hidden

    def root_now(snap: Optional[InteractionSnapshot]) -> WidgetNode:
        return _state(snap, root.selector) or root

    s = [_after(run, k) for k in range(9)]
    snaps = [x for x in [_after(run, -1), *s] if x is not None]

    resolved: Optional[WidgetNode] = at_load
    if pid is not None and resolved is None:
        resolved = next((n for n in (_node_by_id(x, pid) for x in snaps) if n is not None), None)
    if pid is None:
        v["controls-a-popup"] = ("cantTell", "no aria-controls or aria-owns; the popup cannot be located")
    elif resolved is not None:
        v["controls-a-popup"] = (
            ("pass", f"references {resolved.selector} (role={resolved.role})") if resolved.role in _POPUP_ROLES
            else ("fail", f"references {resolved.selector}, whose role {resolved.role!r} is not a combobox popup")
        )
    elif any(root_now(x).attributes.get("aria-expanded") == "true" for x in snaps):
        v["controls-a-popup"] = ("fail", f"aria-expanded=true but {pid!r} does not exist")
    else:
        v["controls-a-popup"] = ("cantTell", f"{pid!r} is not in the DOM and the popup was never displayed "
                                             "(it may be rendered lazily)")

    ready_down = s[0] is not None and s[1] is not None and s[0].active == root.selector and is_open(s[0]) is False
    down_opens = ready_down and bool(is_open(s[1]))
    ready_alt = s[4] is not None and s[5] is not None and s[4].active == root.selector and is_open(s[4]) is False
    alt_opens = ready_alt and bool(is_open(s[5]))
    click_opens: Optional[bool] = (
        None if s[6] is None or s[7] is None or is_open(s[6]) is not False else bool(is_open(s[7]))
    )

    if pid is None:
        v["keyboard-opens-popup"] = ("cantTell", "the popup cannot be located, so opening cannot be observed")
    elif s[0] is None or s[1] is None:
        v["keyboard-opens-popup"] = ("cantTell", _missing_snapshot(run))
    elif not ready_down:
        v["keyboard-opens-popup"] = ("cantTell", "precondition not met: combobox focused with the popup closed")
    elif down_opens:
        v["keyboard-opens-popup"] = ("pass", "ArrowDown displays the popup")
    elif alt_opens:
        v["keyboard-opens-popup"] = ("pass", "Alt+ArrowDown displays the popup (ArrowDown does not)")
    elif not ready_alt or click_opens is None:
        v["keyboard-opens-popup"] = ("cantTell", "ArrowDown did not open the popup, and Alt+ArrowDown or a click "
                                                 "could not be compared")
    elif click_opens:
        v["keyboard-opens-popup"] = ("fail", "a click displays the popup, but neither ArrowDown nor Alt+ArrowDown does")
    else:
        v["keyboard-opens-popup"] = ("cantTell", "neither ArrowDown, Alt+ArrowDown nor a click displays the popup — "
                                                 "it may need typing first; not a keyboard-only difference")

    open_snaps = [x for x in snaps if is_open(x)]
    if pid is None:
        v["expanded-true-when-open"] = ("cantTell", "the popup cannot be located")
    elif not open_snaps:
        v["expanded-true-when-open"] = ("cantTell", "the popup was never displayed")
    else:
        bad = [x.step_index for x in open_snaps if root_now(x).attributes.get("aria-expanded") != "true"]
        v["expanded-true-when-open"] = (
            ("fail", f"popup displayed without aria-expanded=true after step(s) {bad}") if bad
            else ("pass", "aria-expanded=true whenever the popup is displayed")
        )

    editable = root.tag in ("input", "textarea")
    popup_role = resolved.role if resolved is not None else None
    opt_ids = {o.attributes["id"] for o in options if o.attributes.get("id")}
    opt_sels = {o.selector for o in options}
    if not down_opens or s[1] is None or s[2] is None:
        v["arrow-keys-reach-options"] = ("cantTell", "precondition not met: ArrowDown opened the popup")
    elif popup_role != "listbox":
        v["arrow-keys-reach-options"] = ("cantTell", f"popup role is {popup_role!r}; option navigation is "
                                                     "checked for listbox popups only")
    else:
        verified, unverified = [], []
        for x in (s[1], s[2]):
            ad = (root_now(x).attributes.get("aria-activedescendant") or "").strip()
            if x.active in opt_sels or (ad and ad in opt_ids):
                verified.append(x.active if x.active in opt_sels else ad)
            elif ad or (x.active not in (None, root.selector)):
                unverified.append(ad or x.active)
        if verified:
            v["arrow-keys-reach-options"] = ("pass", f"ArrowDown made an option active ({verified[-1]})")
        elif unverified:
            v["arrow-keys-reach-options"] = ("cantTell", f"ArrowDown moved to {unverified[-1]!r}, which is not "
                                                         "an option known at scan time")
        else:
            v["arrow-keys-reach-options"] = (
                "fail", "with the listbox open, ArrowDown made no option active "
                        "(no aria-activedescendant, no focus on an option)",
                *((APG_ONLY,) if editable else ()))

    if not down_opens or s[1] is None or s[2] is None:
        v["focus-stays-on-combobox"] = ("cantTell", "precondition not met: ArrowDown opened the popup")
    elif popup_role == "dialog":
        # A date-picker dialog takes focus by design (APG combobox-datepicker).
        v["focus-stays-on-combobox"] = ("cantTell", "the popup is a dialog, which takes focus by design")
    elif s[1].active == root.selector and s[2].active == root.selector:
        v["focus-stays-on-combobox"] = ("pass", "DOM focus stayed on the combobox")
    else:
        moved = s[2].active if s[2].active != root.selector else s[1].active
        v["focus-stays-on-combobox"] = ("fail", f"DOM focus moved to {moved or 'the page'}")

    if s[2] is None or s[3] is None or not is_open(s[2]):
        v["escape-closes-popup"] = ("cantTell", "precondition not met: popup open before Escape")
    elif is_open(s[3]) is False:
        v["escape-closes-popup"] = ("pass", "Escape hid the popup")
    else:
        v["escape-closes-popup"] = ("fail", "Escape did not hide the popup")
    return v


CHECKS: dict[str, PatternChecks] = {
    "tablist": PatternChecks(_tablist_plan, _tablist_evaluate),
    "disclosure": PatternChecks(_disclosure_plan, _disclosure_evaluate),
    "menu-button": PatternChecks(_menu_button_plan, _menu_button_evaluate),
    "dialog": PatternChecks(_dialog_plan, _dialog_evaluate, watch=_dialog_watch),
    "combobox": PatternChecks(_combobox_plan, _combobox_evaluate, watch=_combobox_watch),
}


# --- the runner -------------------------------------------------------------

def _watch(widget: Widget, checks: Optional[PatternChecks] = None) -> list[str]:
    seen: list[str] = []
    extra = checks.watch(widget) if checks is not None and checks.watch is not None else []
    for sel in (*(n.selector for n in (widget.root, *widget.items, *widget.related)), *extra):
        if sel not in seen:
            seen.append(sel)
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
    started = time.monotonic()

    for widget in inventory.widgets:
        for contract in contracts.values():
            if not matches(contract.match, widget):
                continue
            out.widgets_matched[contract.contract] += 1
            if widget.root.hidden:
                # Not rendered at scan time (a mobile-only nav duplicate, a
                # closed panel's contents): nothing a user can operate now.
                for section in ("structure", "keyboard"):
                    for a in getattr(contract, section):
                        out.results.append(AssertionResult(
                            contract=contract.contract, assertion_id=a.id, severity=a.severity,
                            wcag=a.wcag, section=section, widget=widget.root.selector,
                            outcome="notChecked", detail="widget not rendered at scan time",
                        ))
                continue
            if (exercised >= budget.max_widgets
                    or (time.monotonic() - started) * 1000 > budget.max_ms_per_page):
                out.widgets_skipped.append(widget.root.selector)
                continue
            exercised += 1

            checks = CHECKS.get(contract.contract)
            steps = checks.plan(widget) if checks else []
            run: Optional[ExerciseResult] = None
            if steps:
                try:
                    run = await exercise(widget, steps, _watch(widget, checks), budget)
                except Exception as exc:
                    logger.info(
                        "exerciseWidget unavailable for %s (%s); driven checks are cantTell.",
                        widget.root.selector,
                        exc.__class__.__name__,
                    )
                if run is not None and run.self_changing:
                    # Autoplay: effects after a key may be the timer's. The
                    # static checks still stand; the driven ones cannot judge.
                    run = run.model_copy(update={
                        "snapshots": [],
                        "complete": False,
                        "incomplete_reason": "the widget changes on its own (autoplay or animation), "
                                             "so effects cannot be attributed to keys",
                    })
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
                verdict = verdicts.get(
                    aid,
                    ("notChecked", "no check is implemented for this assertion" if checks
                     else "no checks are implemented for this contract"),
                )
                outcome, detail = verdict[0], verdict[1]
                severity = assertion.severity
                if len(verdict) > 2 and verdict[2] == APG_ONLY:
                    severity = Severity.WARNING
                    detail = f"APG deviation, not a WCAG barrier: {detail}"
                out.results.append(AssertionResult(
                    contract=contract.contract,
                    assertion_id=aid,
                    severity=severity,
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
