"""
A14.3 — the complete injector catalog, prevalence-weighted.

Eight injector modules accumulated across Weeks 1–9, each built for a specific
gate. This is the catalog that pulls them into one set and weights it to the
real web, so the benchmark and `verity agent-check` can inject a mix that looks
like what sites actually ship, not an arbitrary one.

Each entry records the WCAG success criterion the defect creates, its defect
family, a default selector, and — where WebAIM measured it — its **home-page
prevalence** (WebAIM Million 2026, the figures the pre-registration cites: low
contrast 83.9%, missing alt 53.1%, missing form labels 51%, empty links 46.3%,
empty buttons 30.6%). The agent-relevant defects that break the accessibility
tree for an agent but that WebAIM does not score (div-button, roving-tabindex,
keyboard traps) carry `prevalence=None` — kept in the catalog, excluded from the
prevalence-weighted mix, and said so, rather than invented.

Every injector shares the package contract `inject(html, selector) ->
html` / `revert(...)`, so the catalog treats them uniformly. `empty_link` and
`empty_button` are `strip_accessible_name` scoped to links / buttons — the two
defects WebAIM reports separately — not new code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from eval.inject import (
    common_defects,
    contrast_over_image,
    detach_label,
    keyboard_trap,
    outline_none,
    positive_tabindex,
    reduce_contrast,
    strip_alt,
)
from eval.inject.aria_misuse import (
    click_only_widget,
    dangling_idref,
    invalid_aria_state,
    remove_from_tab_order,
    strip_accessible_name,
    wrong_role,
)

WEBAIM = "WebAIM Million 2026 (home-page prevalence)"
NOT_SCORED = "not scored by WebAIM Million (agent-relevant; tree-only)"


@dataclass(frozen=True)
class InjectorSpec:
    """One injector plus what it means and how common it is."""

    id: str
    sc: str                 # WCAG SC id, e.g. "4.1.2"
    sc_name: str
    level: str              # "A" | "AA" | "AAA"
    family: str             # name | contrast | keyboard | focus | structure | language
    default_selector: str
    prevalence: Optional[float]   # fraction of pages, or None if unmeasured
    source: str
    _inject: Callable[..., str]
    _revert: Callable[..., str]

    def inject(self, html: str, selector: Optional[str] = None) -> str:
        return self._inject(html, selector or self.default_selector)

    def revert(self, html: str, selector: Optional[str] = None) -> str:
        return self._revert(html, selector or self.default_selector)


def _spec(id, sc, sc_name, level, family, selector, prevalence, source, impl) -> InjectorSpec:
    return InjectorSpec(id, sc, sc_name, level, family, selector, prevalence, source,
                        impl.inject, impl.revert)


CATALOG: dict[str, InjectorSpec] = {s.id: s for s in (
    # --- WebAIM top defects (prevalence-weighted) ---------------------------
    _spec("low_contrast", "1.4.3", "Contrast (Minimum)", "AA", "contrast",
          "body", 0.839, WEBAIM, reduce_contrast),
    _spec("missing_alt", "1.1.1", "Non-text Content", "A", "name",
          "img", 0.531, WEBAIM, strip_alt),
    _spec("missing_form_label", "4.1.2", "Name, Role, Value", "A", "name",
          "label", 0.510, WEBAIM, detach_label),
    _spec("empty_link", "4.1.2", "Name, Role, Value", "A", "name",
          "a[href]", 0.463, WEBAIM, strip_accessible_name),
    _spec("empty_button", "4.1.2", "Name, Role, Value", "A", "name",
          "button", 0.306, WEBAIM, strip_accessible_name),
    _spec("missing_document_language", "3.1.1", "Language of Page", "A", "language",
          "html", 0.170, WEBAIM + " (document-language family)", common_defects),
    _spec("contrast_over_image", "1.4.3", "Contrast (Minimum)", "AA", "contrast",
          "body", None, "subset of low contrast; the axe-incomplete wedge (W3)", contrast_over_image),
    # --- agent-relevant / APG defects (not prevalence-weighted) -------------
    _spec("div_button", "4.1.2", "Name, Role, Value", "A", "name",
          "button", None, NOT_SCORED, click_only_widget),
    _spec("strip_accessible_name", "4.1.2", "Name, Role, Value", "A", "name",
          "button, a[href]", None, NOT_SCORED, strip_accessible_name),
    _spec("invalid_aria_state", "4.1.2", "Name, Role, Value", "A", "name",
          "[aria-expanded]", None, NOT_SCORED, invalid_aria_state),
    _spec("dangling_idref", "1.3.1", "Info and Relationships", "A", "structure",
          "[aria-controls]", None, NOT_SCORED, dangling_idref),
    _spec("wrong_role", "1.3.1", "Info and Relationships", "A", "structure",
          "[role]", None, NOT_SCORED, wrong_role),
    _spec("remove_from_tab_order", "2.1.1", "Keyboard", "A", "keyboard",
          "[role='tab']", None, NOT_SCORED, remove_from_tab_order),
    _spec("keyboard_trap", "2.1.2", "No Keyboard Trap", "A", "keyboard",
          "input", None, NOT_SCORED, keyboard_trap),
    _spec("positive_tabindex", "2.4.3", "Focus Order", "A", "keyboard",
          "[tabindex]", None, NOT_SCORED, positive_tabindex),
    _spec("outline_none", "2.4.7", "Focus Visible", "AA", "focus",
          "a, button, input", None, NOT_SCORED, outline_none),
)}


def by_family(family: str) -> list[InjectorSpec]:
    return [s for s in CATALOG.values() if s.family == family]


def by_sc(sc: str) -> list[InjectorSpec]:
    return [s for s in CATALOG.values() if s.sc == sc]


def prevalence_weighted() -> list[InjectorSpec]:
    """The injectors WebAIM measured, most common first — the real-web mix."""
    scored = [s for s in CATALOG.values() if s.prevalence is not None]
    return sorted(scored, key=lambda s: s.prevalence, reverse=True)


def prevalence_weights() -> dict[str, float]:
    """
    Normalised sampling weights over the prevalence-measured injectors (they sum
    to 1). Use these to draw an injector mix that matches the real web instead
    of testing every defect equally — a benchmark that over-weights a rare
    defect over-states its importance.
    """
    scored = {s.id: s.prevalence for s in CATALOG.values() if s.prevalence is not None}
    total = sum(scored.values())
    return {k: v / total for k, v in scored.items()} if total else {}


def summary() -> dict:
    """Shape of the catalog: counts, families, how many are prevalence-weighted."""
    families: dict[str, int] = {}
    for s in CATALOG.values():
        families[s.family] = families.get(s.family, 0) + 1
    scored = [s for s in CATALOG.values() if s.prevalence is not None]
    return {
        "injectors": len(CATALOG),
        "families": families,
        "prevalence_weighted": len(scored),
        "agent_relevant_unscored": len(CATALOG) - len(scored),
    }
