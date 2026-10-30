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
}

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

    b, a = parse_tree(before), parse_tree(after)
    effect = _DEFECT_EFFECT[defect]
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
    env.reset(task, seed, defect=None)
    clean_tree = env.observe()
    clean_png = env.screenshot()

    env.reset(task, seed, defect=defect)
    defect_tree = env.observe()
    defect_png = env.screenshot()

    assessment = assess_change(clean_tree, defect_tree, defect)
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
