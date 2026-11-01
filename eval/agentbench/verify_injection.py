"""
A11.2′ — injection verification.

Before a (task × defect) variant is used in the benchmark, Verity must assert
that it carries **exactly the intended defect, and nothing else**. A variant
that fails verification is aborted, not measured — otherwise a cell's result is
uninterpretable: did the agent fail because of the defect we meant to inject,
or because the injection also broke something else, or did it not inject at all?

Two assertions, both deterministic:

1. **The defect manifested, in the accessibility tree, in the expected
   direction.** `strip_name` / `detach_label` remove an accessible name from a
   control; `div_button` removes the `button` role and leaves a roleless
   clickable in its place. We read the agent's own view (the AXTree the env
   renders) and check the named-control / button counts moved the right way.
   No change → the injection silently did nothing → abort.

2. **The pixels did not change.** Every defect in `defects.js` is designed to be
   invisible to a sighted user — that is what makes a behaviour difference
   attributable to the accessibility tree rather than to a visual change. So a
   clean and a defect render of the same seed must be pixel-identical. If they
   differ, the defect is visible and the variant is confounded → abort.

The tree assessment is pure and tested without a browser; `verify()` drives the
real env and adds the pixel check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# Roles that carry an actionable, nameable control in the AXTree observation.
_NAMEABLE_CONTROL = frozenset({
    "button", "link", "textbox", "checkbox", "radio", "combobox", "listbox",
    "menuitem", "searchbox", "slider", "switch", "spinbutton",
})

# What each defect is expected to do to the tree.
#   name_loss  — a named control loses its accessible name
#   role_loss  — a button loses its role (a roleless clickable appears)
_DEFECT_EFFECT = {
    "strip_name": "name_loss",
    "detach_label": "name_loss",
    "div_button": "role_loss",
    # Keyboard / focus family (H3). These do not change the tree at all, so
    # they are verified by DRIVING the keyboard: a Tab probe on the clean and
    # the defect page, compared (`assess_keyboard`).
    "keyboard_trap": "trap",
    "remove_from_tab_order": "tab_loss",
    "outline_none": "focus_indicator_loss",
}
KEYBOARD_EFFECTS = frozenset({"trap", "tab_loss", "focus_indicator_loss"})
TAB_PRESSES = 6

# Where focus is after a key press, and whether it is visibly indicated.
_ACTIVE_JS = """() => {
  const a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return {id: null, indicator: false};
  let id = a.id ? '#' + a.id : a.tagName.toLowerCase();
  if (!a.id) { const sib = Array.from(a.parentElement ? a.parentElement.children : []); id += ':' + sib.indexOf(a); }
  const cs = getComputedStyle(a);
  const outline = cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0;
  const shadow = cs.boxShadow && cs.boxShadow !== 'none';
  return {id, indicator: !!(outline || shadow)};
}"""

# One AXTree observation line: `  [12] button "Save" (focused)` / `generic "x" (clickable)`.
_LINE = re.compile(r'^\s*(?:\[(\d+)\]\s*)?([A-Za-z]+)(?:\s+"([^"]*)")?(.*)$')


@dataclass
class ParsedNode:
    bid: Optional[str]
    role: str
    name: str
    clickable: bool


def parse_tree(observation: str) -> list[ParsedNode]:
    """Parse an AXTree observation into nodes. Lines that don't match are skipped."""
    nodes: list[ParsedNode] = []
    for line in observation.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        bid, role, name, rest = m.groups()
        nodes.append(ParsedNode(bid=bid, role=role, name=(name or ""), clickable="(clickable)" in (rest or "")))
    return nodes


def _named_controls(nodes: list[ParsedNode]) -> int:
    return sum(1 for n in nodes if n.role in _NAMEABLE_CONTROL and n.name.strip())


def _buttons(nodes: list[ParsedNode]) -> int:
    return sum(1 for n in nodes if n.role == "button")


def _roleless_clickables(nodes: list[ParsedNode]) -> int:
    return sum(1 for n in nodes if n.role in ("generic", "GenericContainer", "") and n.clickable)


@dataclass
class ChangeAssessment:
    """Whether the tree changed as the defect intends."""

    defect: str
    manifested: bool
    detail: str
    before_named: int = 0
    after_named: int = 0


def assess_change(before: str, after: str, defect: str) -> ChangeAssessment:
    """Did the AXTree change in the direction `defect` intends? (pure)"""
    if defect not in _DEFECT_EFFECT:
        return ChangeAssessment(defect, False, f"unknown defect {defect!r}")

    effect = _DEFECT_EFFECT[defect]
    if effect in KEYBOARD_EFFECTS:
        return ChangeAssessment(defect, False, "a keyboard defect does not change the tree; verify it with "
                                               "tab_probe + assess_keyboard")
    b, a = parse_tree(before), parse_tree(after)
    bn, an = _named_controls(b), _named_controls(a)

    if effect == "name_loss":
        manifested = an < bn
        detail = f"named controls {bn} -> {an}" + ("" if manifested else " (no name was lost)")
        return ChangeAssessment(defect, manifested, detail, bn, an)

    # role_loss (div_button): fewer buttons, and a roleless clickable appeared.
    buttons_before, buttons_after = _buttons(b), _buttons(a)
    clickables_before, clickables_after = _roleless_clickables(b), _roleless_clickables(a)
    manifested = buttons_after < buttons_before and clickables_after > clickables_before
    detail = (f"buttons {buttons_before} -> {buttons_after}, "
              f"roleless-clickables {clickables_before} -> {clickables_after}")
    return ChangeAssessment(defect, manifested, detail, bn, an)


def tab_probe(page, presses: int = TAB_PRESSES) -> list[dict]:
    """Press Tab from the top of the page `presses` times; record focus and its indicator after each."""
    page.evaluate("() => { if (document.activeElement) document.activeElement.blur(); }")
    out = []
    for _ in range(presses):
        page.keyboard.press("Tab")
        out.append(page.evaluate(_ACTIVE_JS))
    return out


def assess_keyboard(clean: list[dict], defect: list[dict], name: str) -> "ChangeAssessment":
    """Did driving the keyboard behave as the defect intends? (pure)"""
    effect = _DEFECT_EFFECT.get(name)
    ids_c = {p["id"] for p in clean if p.get("id")}
    ids_d = {p["id"] for p in defect if p.get("id")}
    if effect == "trap":
        manifested = len(ids_c) >= 2 and len(ids_d) == 1
        detail = f"distinct focus stops clean {len(ids_c)} -> defect {len(ids_d)}"
    elif effect == "tab_loss":
        manifested = len(ids_d) < len(ids_c)
        detail = f"distinct focus stops clean {len(ids_c)} -> defect {len(ids_d)}"
    elif effect == "focus_indicator_loss":
        had = any(p.get("indicator") for p in clean)
        manifested = had and not any(p.get("indicator") for p in defect)
        detail = f"visible focus indicator clean {'yes' if had else 'no'} -> defect " \
                 f"{'no' if manifested else 'yes'}"
    else:
        return ChangeAssessment(name, False, f"{name!r} is not a keyboard defect")
    if not ids_c:
        manifested, detail = False, "the clean page has nothing focusable; the defect cannot be verified"
    return ChangeAssessment(name, manifested, detail)


@dataclass
class VerifyResult:
    task: str
    seed: int
    defect: str
    ok: bool
    reasons: list[str] = field(default_factory=list)
    assessment: Optional[ChangeAssessment] = None
    pixels_identical: Optional[bool] = None


def verify(env, task: str, seed: int, defect: str) -> VerifyResult:
    """
    Drive the real env: render clean and defect at the same seed, assert the
    defect manifested in the tree and the pixels are identical. The caller
    aborts the variant when `ok` is False.
    """
    keyboard = _DEFECT_EFFECT.get(defect) in KEYBOARD_EFFECTS

    env.reset(task, seed, defect=None)
    clean_tree = env.observe()
    clean_png = env.screenshot()
    clean_probe = tab_probe(env.page) if keyboard else None

    env.reset(task, seed, defect=defect)
    defect_tree = env.observe()
    defect_png = env.screenshot()          # before any key press: nothing focused yet
    defect_probe = tab_probe(env.page) if keyboard else None

    assessment = (assess_keyboard(clean_probe, defect_probe, defect) if keyboard
                  else assess_change(clean_tree, defect_tree, defect))
    pixels_identical = clean_png == defect_png

    reasons: list[str] = []
    if not assessment.manifested:
        reasons.append(f"defect did not manifest in the tree: {assessment.detail}")
    if not pixels_identical:
        reasons.append("clean and defect renders differ in pixels — the defect is visible, "
                       "so a behaviour difference would be confounded")

    return VerifyResult(
        task=task, seed=seed, defect=defect,
        ok=assessment.manifested and pixels_identical,
        reasons=reasons, assessment=assessment, pixels_identical=pixels_identical,
    )
