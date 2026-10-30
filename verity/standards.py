"""
The WCAG 2.2 success-criteria table — 87 rows (86 in force + 4.1.1, obsolete)
— and what Verity does about each one.

Used by two Track B deliverables:

- **B14.3 coverage metric** (`coverage_summary`): the fraction of the 86
  criteria Verity attempts at all, by how it attempts them — published
  honestly, gaps included.
- **B16.1–B16.3 the ACR/VPAT** (`verity.acr`): every criterion gets a row,
  including the ones nobody can test automatically.

How Verity tests a criterion (`Method`):

- `deterministic` — Verity's own measurement can decide a FAILURE
  authoritatively (contrast from real pixels, keyboard traversal, APG
  contracts) and axe rules contribute too;
- `automated-partial` — automated rules (axe-core, WCAG-tagged) catch some
  failures; a pass still needs a human, because the rule cannot see every way
  the criterion can fail;
- `manual` — no automated check exists or is meaningful (captions quality,
  reading level, consistent help…). Never reported as passing.

A criterion's method is a claim, so it is stated conservatively: a criterion
appears here as tested only if a shipped check emits findings tagged with it.
`AXE_SC` is pinned against the axe-core version in `node-worker/package.json`;
`verity/tests/test_standards.py` re-derives it from axe's own rule tags when
the worker is installed and fails if the two drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

Level = Literal["A", "AA", "AAA"]
Method = Literal["deterministic", "automated-partial", "manual"]


@dataclass(frozen=True)
class Criterion:
    id: str
    name: str
    level: Level
    obsolete: bool = False


WCAG22: tuple[Criterion, ...] = (
    Criterion("1.1.1", "Non-text Content", "A"),
    Criterion("1.2.1", "Audio-only and Video-only (Prerecorded)", "A"),
    Criterion("1.2.2", "Captions (Prerecorded)", "A"),
    Criterion("1.2.3", "Audio Description or Media Alternative (Prerecorded)", "A"),
    Criterion("1.2.4", "Captions (Live)", "AA"),
    Criterion("1.2.5", "Audio Description (Prerecorded)", "AA"),
    Criterion("1.2.6", "Sign Language (Prerecorded)", "AAA"),
    Criterion("1.2.7", "Extended Audio Description (Prerecorded)", "AAA"),
    Criterion("1.2.8", "Media Alternative (Prerecorded)", "AAA"),
    Criterion("1.2.9", "Audio-only (Live)", "AAA"),
    Criterion("1.3.1", "Info and Relationships", "A"),
    Criterion("1.3.2", "Meaningful Sequence", "A"),
    Criterion("1.3.3", "Sensory Characteristics", "A"),
    Criterion("1.3.4", "Orientation", "AA"),
    Criterion("1.3.5", "Identify Input Purpose", "AA"),
    Criterion("1.3.6", "Identify Purpose", "AAA"),
    Criterion("1.4.1", "Use of Color", "A"),
    Criterion("1.4.2", "Audio Control", "A"),
    Criterion("1.4.3", "Contrast (Minimum)", "AA"),
    Criterion("1.4.4", "Resize Text", "AA"),
    Criterion("1.4.5", "Images of Text", "AA"),
    Criterion("1.4.6", "Contrast (Enhanced)", "AAA"),
    Criterion("1.4.7", "Low or No Background Audio", "AAA"),
    Criterion("1.4.8", "Visual Presentation", "AAA"),
    Criterion("1.4.9", "Images of Text (No Exception)", "AAA"),
    Criterion("1.4.10", "Reflow", "AA"),
    Criterion("1.4.11", "Non-text Contrast", "AA"),
    Criterion("1.4.12", "Text Spacing", "AA"),
    Criterion("1.4.13", "Content on Hover or Focus", "AA"),
    Criterion("2.1.1", "Keyboard", "A"),
    Criterion("2.1.2", "No Keyboard Trap", "A"),
    Criterion("2.1.3", "Keyboard (No Exception)", "AAA"),
    Criterion("2.1.4", "Character Key Shortcuts", "A"),
    Criterion("2.2.1", "Timing Adjustable", "A"),
    Criterion("2.2.2", "Pause, Stop, Hide", "A"),
    Criterion("2.2.3", "No Timing", "AAA"),
    Criterion("2.2.4", "Interruptions", "AAA"),
    Criterion("2.2.5", "Re-authenticating", "AAA"),
    Criterion("2.2.6", "Timeouts", "AAA"),
    Criterion("2.3.1", "Three Flashes or Below Threshold", "A"),
    Criterion("2.3.2", "Three Flashes", "AAA"),
    Criterion("2.3.3", "Animation from Interactions", "AAA"),
    Criterion("2.4.1", "Bypass Blocks", "A"),
    Criterion("2.4.2", "Page Titled", "A"),
    Criterion("2.4.3", "Focus Order", "A"),
    Criterion("2.4.4", "Link Purpose (In Context)", "A"),
    Criterion("2.4.5", "Multiple Ways", "AA"),
    Criterion("2.4.6", "Headings and Labels", "AA"),
    Criterion("2.4.7", "Focus Visible", "AA"),
    Criterion("2.4.8", "Location", "AAA"),
    Criterion("2.4.9", "Link Purpose (Link Only)", "AAA"),
    Criterion("2.4.10", "Section Headings", "AAA"),
    Criterion("2.4.11", "Focus Not Obscured (Minimum)", "AA"),
    Criterion("2.4.12", "Focus Not Obscured (Enhanced)", "AAA"),
    Criterion("2.4.13", "Focus Appearance", "AAA"),
    Criterion("2.5.1", "Pointer Gestures", "A"),
    Criterion("2.5.2", "Pointer Cancellation", "A"),
    Criterion("2.5.3", "Label in Name", "A"),
    Criterion("2.5.4", "Motion Actuation", "A"),
    Criterion("2.5.5", "Target Size (Enhanced)", "AAA"),
    Criterion("2.5.6", "Concurrent Input Mechanisms", "AAA"),
    Criterion("2.5.7", "Dragging Movements", "AA"),
    Criterion("2.5.8", "Target Size (Minimum)", "AA"),
    Criterion("3.1.1", "Language of Page", "A"),
    Criterion("3.1.2", "Language of Parts", "AA"),
    Criterion("3.1.3", "Unusual Words", "AAA"),
    Criterion("3.1.4", "Abbreviations", "AAA"),
    Criterion("3.1.5", "Reading Level", "AAA"),
    Criterion("3.1.6", "Pronunciation", "AAA"),
    Criterion("3.2.1", "On Focus", "A"),
    Criterion("3.2.2", "On Input", "A"),
    Criterion("3.2.3", "Consistent Navigation", "AA"),
    Criterion("3.2.4", "Consistent Identification", "AA"),
    Criterion("3.2.5", "Change on Request", "AAA"),
    Criterion("3.2.6", "Consistent Help", "A"),
    Criterion("3.3.1", "Error Identification", "A"),
    Criterion("3.3.2", "Labels or Instructions", "A"),
    Criterion("3.3.3", "Error Suggestion", "AA"),
    Criterion("3.3.4", "Error Prevention (Legal, Financial, Data)", "AA"),
    Criterion("3.3.5", "Help", "AAA"),
    Criterion("3.3.6", "Error Prevention (All)", "AAA"),
    Criterion("3.3.7", "Redundant Entry", "A"),
    Criterion("3.3.8", "Accessible Authentication (Minimum)", "AA"),
    Criterion("3.3.9", "Accessible Authentication (Enhanced)", "AAA"),
    Criterion("4.1.1", "Parsing (obsolete and removed in WCAG 2.2)", "A", obsolete=True),
    Criterion("4.1.2", "Name, Role, Value", "A"),
    Criterion("4.1.3", "Status Messages", "AA"),
)

BY_ID = {c.id: c for c in WCAG22}

# Level A/AA criteria that axe-core's non-experimental WCAG-tagged rules report
# on (derived from axe-core 4.13's own rule tags, 2026-10-30). Verity keeps
# only WCAG-tagged axe results, so this is what the axe stage can touch. AAA
# rules (color-contrast-enhanced, …) are left out on purpose: the report's
# target is WCAG 2.2 AA, and a AAA rule is not a claim about it.
AXE_SC = frozenset({
    "1.1.1", "1.2.2", "1.3.1", "1.3.5", "1.4.1", "1.4.2", "1.4.3", "1.4.4", "1.4.12", "2.1.1", "2.2.1",
    "2.2.2", "2.4.1", "2.4.2", "2.4.4", "2.5.8", "3.1.1", "3.1.2", "3.3.2", "4.1.2",
})

# Criteria where Verity's OWN measurement decides failures authoritatively.
VERITY_DETERMINISTIC = {
    "1.4.3": "contrast from real rendered pixels, including text over images and gradients",
    "2.1.1": "keyboard traversal + APG widget contracts (keys actually pressed)",
    "2.1.2": "multi-cycle keyboard-trap detection",
    "2.4.3": "observed tab order vs DOM order, positive tabindex",
    "2.4.7": "focus indicator measured per tab stop (style diff + pixel diff)",
    "4.1.2": "APG widget contracts; agent-check confirmation (B14.1′)",
}

# Model-assisted checks exist for these but are flag-gated (ADR-0002); they
# never make a criterion "tested" in the conformance sense.
VISION_FLAGGED = {"1.1.1": "alt-text meaningfulness (experiment)", "1.4.5": "text in images (experiment)"}


def method(sc_id: str) -> Method:
    if sc_id in VERITY_DETERMINISTIC:
        return "deterministic"
    if sc_id in AXE_SC:
        return "automated-partial"
    return "manual"


def how_tested(sc_id: str) -> str:
    """Plain-language description of what Verity does for this criterion."""
    parts = []
    if sc_id in VERITY_DETERMINISTIC:
        parts.append(VERITY_DETERMINISTIC[sc_id])
    if sc_id in AXE_SC:
        parts.append("axe-core rules")
    if not parts:
        return "not tested automatically; requires human evaluation"
    return "; ".join(parts)


def active() -> list[Criterion]:
    return [c for c in WCAG22 if not c.obsolete]


def coverage_summary(levels: tuple[str, ...] = ("A", "AA", "AAA")) -> dict:
    """
    B14.3 — how many of the active criteria Verity attempts, by method, per
    level. Gaps are listed, not hidden.
    """
    rows = [c for c in active() if c.level in levels]
    by_method: dict[str, list[str]] = {"deterministic": [], "automated-partial": [], "manual": []}
    for c in rows:
        by_method[method(c.id)].append(c.id)
    attempted = len(by_method["deterministic"]) + len(by_method["automated-partial"])
    return {
        "criteria": len(rows),
        "attempted": attempted,
        "attempted_share": attempted / len(rows) if rows else 0.0,
        "by_method": {k: len(v) for k, v in by_method.items()},
        "deterministic": by_method["deterministic"],
        "automated_partial": by_method["automated-partial"],
        "not_attempted": by_method["manual"],
    }


def criterion(sc_id: str) -> Optional[Criterion]:
    return BY_ID.get(sc_id)
