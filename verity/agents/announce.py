"""
B9.1 — announcement prediction (Track B, Week 9).

What would a screen reader say when it lands on this element? Real screen
readers are excluded from CI on purpose (execution plan, Week 4 "Learning"
and the deferred list): they are fragile, platform-bound, and turn the
highest-risk dependency in the pipeline into a flaky one. So we predict the
announcement instead, as a **pure function** of three things the browser has
already computed:

- the accessible **name** — Chromium's `computeAccessibleName`, read from the
  accessibility tree (render.ts saves it as `ax-tree.json`; the widget
  inventory takes it per node, see node-worker/interaction/accname.ts);
- the **role**;
- the **states** (expanded, selected, checked, pressed, disabled, …).

The output is screen-reader-neutral, in the order NVDA/JAWS/VoiceOver all
broadly share: name, role, then states — e.g. "Show details, button,
collapsed". It is not any one product's exact wording, and nothing here
claims it is. What it is good for is the question a contract actually asks:
*would a screen reader user be told this?* An unnamed button announces as
just "button"; an expandable without aria-expanded never says "collapsed".

No model, no I/O. Same input, same output, on every platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from verity.models.schemas import WidgetNode

# Chromium/ARIA role -> the spoken role. Anything not listed is spoken as its
# role name; structural roles that screen readers do not announce map to "".
ROLE_PHRASES: dict[str, str] = {
    "button": "button",
    "link": "link",
    "heading": "heading",
    "textbox": "edit",
    "searchbox": "search edit",
    "combobox": "combo box",
    "listbox": "list box",
    "option": "option",
    "checkbox": "checkbox",
    "radio": "radio button",
    "switch": "switch",
    "slider": "slider",
    "spinbutton": "spin button",
    "tab": "tab",
    "tablist": "tab list",
    "tabpanel": "tab panel",
    "menu": "menu",
    "menubar": "menu bar",
    "menuitem": "menu item",
    "menuitemcheckbox": "menu item checkbox",
    "menuitemradio": "menu item radio",
    "dialog": "dialog",
    "alertdialog": "alert dialog",
    "img": "graphic",
    "image": "graphic",
    "list": "list",
    "listitem": "",
    "navigation": "navigation landmark",
    "main": "main landmark",
    "banner": "banner landmark",
    "contentinfo": "content info landmark",
    "complementary": "complementary landmark",
    "search": "search landmark",
    "region": "region",
    "form": "form",
    "table": "table",
    "row": "row",
    "cell": "cell",
    "gridcell": "cell",
    "columnheader": "column header",
    "rowheader": "row header",
    "tree": "tree view",
    "treeitem": "tree view item",
    "grid": "grid",
    "progressbar": "progress bar",
    "alert": "alert",
    "status": "status",
    # Not announced as a role.
    "generic": "",
    "none": "",
    "presentation": "",
    "paragraph": "",
    "StaticText": "",
    "group": "grouping",
}

# Roles a user operates. Speaking one of these with no name is the defect a
# screen-reader user hears as "button" — and nothing else.
CONTROL_ROLES = frozenset({
    "button", "link", "textbox", "searchbox", "combobox", "listbox", "option",
    "checkbox", "radio", "switch", "slider", "spinbutton", "tab", "menuitem",
    "menuitemcheckbox", "menuitemradio", "treeitem",
})


@dataclass(frozen=True)
class Announcement:
    """One predicted utterance."""
    role: Optional[str]
    name: Optional[str]
    states: tuple[str, ...] = ()
    text: str = ""
    # A control announced with no name: the user hears only its role.
    unnamed_control: bool = False
    # Where it came from — an ax-tree nodeId or a CSS selector — for evidence.
    source: Optional[str] = field(default=None, compare=False)


def _truthy(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        v = value.strip().lower()
        if v == "true":
            return True
        if v == "false":
            return False
    return None


def state_phrases(role: Optional[str], states: Mapping[str, Any]) -> list[str]:
    """
    Turn normalised states into spoken phrases, in a stable order.

    `states` keys follow ARIA without the `aria-` prefix: expanded, selected,
    checked, pressed, disabled, required, invalid, level, haspopup, modal,
    readonly, current. Values may be bools or ARIA strings ("true", "mixed").
    """
    out: list[str] = []

    level = states.get("level")
    if role == "heading" and level not in (None, ""):
        out.append(f"level {level}")

    haspopup = states.get("haspopup")
    if haspopup not in (None, False, "false", ""):
        kind = "menu" if haspopup in (True, "true") else str(haspopup)
        out.append(f"has popup {kind}")

    pressed = states.get("pressed")
    if pressed is not None:
        if str(pressed).lower() == "mixed":
            out.append("half pressed")
        else:
            out.append("pressed" if _truthy(pressed) else "not pressed")

    checked = states.get("checked")
    if checked is not None and role in {"checkbox", "radio", "switch", "menuitemcheckbox",
                                        "menuitemradio", "option", "treeitem"}:
        if str(checked).lower() == "mixed":
            out.append("half checked")
        elif role == "switch":
            out.append("on" if _truthy(checked) else "off")
        else:
            out.append("checked" if _truthy(checked) else "not checked")

    expanded = _truthy(states.get("expanded"))
    if expanded is not None:
        out.append("expanded" if expanded else "collapsed")

    selected = _truthy(states.get("selected"))
    if selected and role in {"tab", "option", "treeitem", "gridcell", "row"}:
        out.append("selected")

    current = states.get("current")
    if current not in (None, False, "false", ""):
        out.append("current page" if current in (True, "true", "page") else f"current {current}")

    if _truthy(states.get("modal")):
        out.append("modal")
    if _truthy(states.get("required")):
        out.append("required")
    invalid = states.get("invalid")
    if invalid not in (None, False, "false", ""):
        out.append("invalid entry")
    if _truthy(states.get("readonly")):
        out.append("read only")
    if _truthy(states.get("disabled")):
        out.append("unavailable")
    return out


def predict(role: Optional[str], name: Optional[str], states: Optional[Mapping[str, Any]] = None,
            source: Optional[str] = None) -> Announcement:
    """
    Predict the announcement for one element.

    >>> predict("button", "Show details", {"expanded": False}).text
    'Show details, button, collapsed'
    >>> predict("button", None).text
    'button'
    """
    states = states or {}
    clean_name = " ".join((name or "").split()) or None
    phrase = ROLE_PHRASES.get(role or "", role or "")
    spoken_states = tuple(state_phrases(role, states))
    parts = [p for p in (clean_name, phrase, *spoken_states) if p]
    return Announcement(
        role=role,
        name=clean_name,
        states=spoken_states,
        text=", ".join(parts),
        unnamed_control=(role in CONTROL_ROLES and clean_name is None),
        source=source,
    )


# ARIA attributes that carry a spoken state, for nodes read from the DOM.
_ARIA_STATES = ("expanded", "selected", "checked", "pressed", "disabled", "required",
                "invalid", "level", "haspopup", "modal", "readonly", "current")


def predict_for_widget_node(node: WidgetNode) -> Announcement:
    """
    The announcement for an inventoried widget node.

    Uses the node's `accessible_name`, which the worker takes from the
    browser's computed name where the node is rendered (B9.1/B9.3). States
    come from the authored aria-* attributes, plus native `disabled`.
    """
    attrs = node.attributes or {}
    states: dict[str, Any] = {k: attrs[f"aria-{k}"] for k in _ARIA_STATES if f"aria-{k}" in attrs}
    if node.disabled:
        states["disabled"] = True
    return predict(node.role, node.accessible_name, states, source=node.selector)
