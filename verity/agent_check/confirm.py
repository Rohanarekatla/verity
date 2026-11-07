"""
B14.1′ — deterministic confirmation for `verity agent-check` (Track B, Week 14).

The Week-14 rule: *an unconfirmed agent failure is never reported as a site
defect.* Localisation (A14.1′) pins an agent failure to a control; this module
decides, from the live page and nothing else, whether that control really
fails WCAG — and only then upgrades the finding to authoritative.

What the confirmer reads, for the localised element, over CDP:

- Chromium's **computed accessibility node** (`Accessibility.getPartialAXTree`):
  role, computed accessible name, ignored, focusable, disabled;
- its **event listeners** (`DOMDebugger.getEventListeners`): does the element
  itself handle `click`?

Two confirmations, each a textbook WCAG failure with no judgment in it:

| Rule | Confirmed when | SC |
|---|---|---|
| `unnamed-control` | the element is a rendered control whose role requires a name (button, link, textbox, checkbox, …) and Chromium computes **no name** | 4.1.2 |
| `roleless-clickable` | the element **has a click listener**, Chromium gives it **no role** (generic / none), and it is **not focusable** — a div-button | 4.1.2 (and unusable by keyboard, 2.1.1) |

Everything else — the element is gone, it now has a name, it is hidden, it
has a role, it has no click handler of its own (cursor:pointer is not
evidence), CDP failed — is `needs-review`. The confirmer is allowed to say
"I don't know" as often as it likes and never allowed to be wrong; Week 14's
gate is **zero wrong confirmations**, measured by `confirmation_metrics` on the
injected corpus, where ground truth is the `data-verity-defect` marker the
injector leaves on every element it broke.

Confirmations are opt-in on the CLI (`verity agent-check --confirm`) until that
gate has been measured at zero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from verity.agent_check.check import ConfirmFn, Localization, default_confirm
from verity.models.schemas import Confidence, Provenance

# Roles for which a missing name is a 4.1.2 failure on its own.
NAME_REQUIRED_ROLES = frozenset({
    "button", "link", "textbox", "searchbox", "checkbox", "radio", "switch", "combobox", "listbox",
    "menuitem", "menuitemcheckbox", "menuitemradio", "tab", "option", "slider", "spinbutton", "treeitem",
})
ROLELESS = frozenset({"generic", "none", "presentation", "", None})


@dataclass
class ElementFacts:
    """What the browser says about one element. Gathered once; decided purely."""
    exists: bool
    role: Optional[str] = None
    name: Optional[str] = None
    ignored: bool = False
    focusable: bool = False
    disabled: bool = False
    click_listener: bool = False
    # Ground truth for measurement only (never used to decide): the
    # `data-verity-defect` marker an injector left on this element or an ancestor.
    defect_marker: Optional[str] = None
    errors: list[str] = field(default_factory=list)


def decide(loc: Localization, facts: Optional[ElementFacts]) -> tuple[str, str]:
    """
    Pure: ("fail", rule) when the facts prove the WCAG failure, else
    ("cantTell", why). Never "pass" — the agent still failed; we only refuse to
    blame the page without proof.
    """
    if facts is None or not facts.exists:
        return "cantTell", "the localised element no longer exists on the page"
    if facts.errors:
        return "cantTell", f"the browser could not describe the element ({facts.errors[0]})"
    if facts.ignored:
        return "cantTell", "the element is not in the accessibility tree (hidden or decorative)"
    if facts.disabled:
        return "cantTell", "the element is disabled"
    name = (facts.name or "").strip()
    if facts.role in NAME_REQUIRED_ROLES:
        if not name:
            return "fail", "unnamed-control"
        return "cantTell", f"the {facts.role} has the accessible name {name!r} now"
    if facts.role in ROLELESS and facts.click_listener and not facts.focusable:
        return "fail", "roleless-clickable"
    if facts.role in ROLELESS and not facts.click_listener:
        return "cantTell", "no click handler on the element itself — not provably a control"
    return "cantTell", f"role {facts.role!r} with name {name!r} is not a provable failure"


def confirm_from_facts(loc: Localization, facts: Optional[ElementFacts]) -> tuple:
    outcome, why = decide(loc, facts)
    if outcome == "fail":
        return (Provenance.AUTHORITATIVE,
                Confidence(score=1.0, method=f"agent-check-confirmed:{why}", model=None, escape_used=False),
                "fail")
    return (Provenance.NEEDS_REVIEW,
            Confidence(score=0.0, method=f"agent-check-unconfirmed:{why}"[:120], model=None, escape_used=True),
            "cantTell")


_FACTS_JS = """function() {
  const el = this;
  let marker = null;
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    if (n.hasAttribute('data-verity-defect')) { marker = n.getAttribute('data-verity-defect'); break; }
  }
  return marker;
}"""


def inspect_element(page, selector: str) -> ElementFacts:
    """Read the facts for `selector` on a live (sync Playwright) page. Never raises."""
    facts = ElementFacts(exists=False)
    try:
        cdp = page.context.new_cdp_session(page)
    except Exception as exc:
        facts.errors.append(f"no CDP session: {exc.__class__.__name__}")
        return facts
    object_id = None
    try:
        import json

        res = cdp.send("Runtime.evaluate", {"expression": f"document.querySelector({json.dumps(selector)})"})
        object_id = (res.get("result") or {}).get("objectId")
        if not object_id:
            return facts
        facts.exists = True
        try:
            nodes = cdp.send("Accessibility.getPartialAXTree", {"objectId": object_id, "fetchRelatives": False})
            node = (nodes.get("nodes") or [{}])[0]
            facts.ignored = bool(node.get("ignored"))
            facts.role = (node.get("role") or {}).get("value")
            facts.name = (node.get("name") or {}).get("value")
            props = {p.get("name"): (p.get("value") or {}).get("value") for p in node.get("properties") or []}
            facts.focusable = props.get("focusable") is True
            facts.disabled = props.get("disabled") is True
        except Exception as exc:
            facts.errors.append(f"accessibility node: {exc.__class__.__name__}")
        try:
            listeners = cdp.send("DOMDebugger.getEventListeners", {"objectId": object_id}).get("listeners") or []
            facts.click_listener = any(l.get("type") == "click" for l in listeners)
        except Exception as exc:
            facts.errors.append(f"event listeners: {exc.__class__.__name__}")
        try:
            marker = cdp.send("Runtime.callFunctionOn", {"objectId": object_id, "functionDeclaration": _FACTS_JS,
                                                         "returnByValue": True})
            facts.defect_marker = (marker.get("result") or {}).get("value")
        except Exception:
            pass
    except Exception as exc:
        facts.errors.append(f"query failed: {exc.__class__.__name__}")
    finally:
        if object_id:
            try:
                cdp.send("Runtime.releaseObject", {"objectId": object_id})
            except Exception:
                pass
        try:
            cdp.detach()
        except Exception:
            pass
    return facts


def make_confirm_fn(env, *, record: Optional[list] = None) -> ConfirmFn:
    """
    A ConfirmFn bound to an env's live page (read when called — the page is
    created by the agent's reset). `record`, if given, collects
    (localization, facts, decision) for measurement.
    """
    def confirm(loc: Localization) -> tuple:
        if not loc.selector or getattr(env, "page", None) is None:
            return default_confirm(loc)
        facts = inspect_element(env.page, loc.selector)
        decision = confirm_from_facts(loc, facts)
        if record is not None:
            record.append({"localization": loc, "facts": facts, "outcome": decision[2]})
        return decision
    return confirm


# --- the Week-14 gate --------------------------------------------------------------

def confirmation_metrics(cases: list[dict]) -> dict:
    """
    The M2 gate on the injected corpus. Each case: `{"defect": str|None,
    "failed": bool, "localized_marker": str|None, "confirmed": bool}` where
    `localized_marker` is the `data-verity-defect` marker found on the
    localised element (ground truth: the injector marks what it broke).

    - localisation rate = failures pinned to an element the injector broke
      (target ≥ 0.80);
    - wrong confirmations = confirmed findings on an element the injector did
      NOT break, or on a clean page (target: exactly 0).
    """
    failures = [c for c in cases if c.get("failed")]
    localized = [c for c in failures if c.get("defect") and c.get("localized_marker")]
    wrong = [c for c in cases if c.get("confirmed") and not (c.get("defect") and c.get("localized_marker"))]
    injected_failures = [c for c in failures if c.get("defect")]
    rate = len(localized) / len(injected_failures) if injected_failures else float("nan")
    return {
        "failures": len(failures), "injected_failures": len(injected_failures),
        "localized": len(localized), "localization_rate": rate,
        "confirmed": sum(1 for c in cases if c.get("confirmed")), "wrong_confirmations": len(wrong),
        "gate_passed": bool(injected_failures) and rate >= 0.80 and not wrong,
    }
