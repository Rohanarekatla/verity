"""
eval/inject/aria_misuse.py — B9.4 (Track B, Week 9)

ARIA-misuse injectors: each takes a correct APG widget and applies exactly
one of the mistakes real sites make, so Week 9's gate can be measured —
*all injected misuse fails; zero false alarms*.

Same contract as the other injectors in this package (see README.md):

- `inject(html, selector, ...)` / `revert(html, selector, ...)`;
- the original value is stashed in a `data-verity-original-*` attribute so
  the transform is reversible, with a marker per injector so two injectors on
  one element cannot clobber each other's backup;
- HTML text is the only tool — no JavaScript context — so each misuse is
  something expressible in markup.

The misuses, and the contract assertion each one must trip:

| injector                | misuse                                         | e.g. fails                         |
|-------------------------|------------------------------------------------|------------------------------------|
| `click_only_widget`     | <button> rebuilt as <div role=button tabindex=0>: looks and announces the same, ignores Enter/Space | disclosure `enter-toggles` |
| `strip_accessible_name` | control left with no text, aria-label, labelledby or title | menu-button `trigger-has-accessible-name` |
| `invalid_aria_state`    | a state attribute given a value AT cannot read ("yes") | disclosure `aria-expanded-is-boolean` |
| `dangling_idref`        | aria-controls pointing at an id that does not exist | menu-button `controls-a-menu` |
| `wrong_role`            | the controlled element given the wrong role    | tablist `controlled-element-is-a-tabpanel` |
| `remove_from_tab_order` | tabindex=-1 on every item of a roving widget   | tablist `roving-tabindex` |

`click_only_widget` is the one that matters most: every static attribute on
the result is correct, and only driving the keys reveals it.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

_ABSENT = "VERITY_ABSENT"
MISSING_ID = "verity-missing-id"


def _stash(el, attr: str, marker: str) -> None:
    el[marker] = el.get(attr, _ABSENT) if el.has_attr(attr) else _ABSENT


def _restore(el, attr: str, marker: str) -> None:
    if not el.has_attr(marker):
        return
    original = el[marker]
    if original == _ABSENT:
        if el.has_attr(attr):
            del el[attr]
    else:
        el[attr] = original
    del el[marker]


def _set_attr(html: str, selector: str, attr: str, value: str, marker: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in soup.select(selector):
        if el.has_attr(marker):  # already injected; keep the true original
            continue
        _stash(el, attr, marker)
        el[attr] = value
    return str(soup)


def _injected(soup, selector: str, marker: str) -> list:
    """
    The elements to revert: those the selector matches AND any carrying this
    injector's marker. The second set matters because some injections change
    what the selector matched on (`wrong_role` rewrites the very role a
    `[role="tabpanel"]` selector looks for; `click_only_widget` the tag).
    """
    found = [el for el in soup.select(selector) if el.has_attr(marker)]
    seen = {id(el) for el in found}  # identity: bs4 Tags compare equal by markup
    found += [el for el in soup.select(f"[{marker}]") if id(el) not in seen]
    return found


def _unset_attr(html: str, selector: str, attr: str, marker: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for el in _injected(soup, selector, marker):
        _restore(el, attr, marker)
    return str(soup)


# --- click_only_widget ----------------------------------------------------------

_TAG_MARKER = "data-verity-original-tag-clickonly"
_ROLE_MARKER_CO = "data-verity-original-role-clickonly"
_TABINDEX_MARKER_CO = "data-verity-original-tabindex-clickonly"


class click_only_widget:  # noqa: N801 — module-style namespace, matches the other injectors' call shape
    """Rebuild a native button as a div: same role and focusability, no keyboard activation."""

    @staticmethod
    def inject(html: str, selector: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for el in soup.select(selector):
            if el.has_attr(_TAG_MARKER):
                continue
            el[_TAG_MARKER] = el.name
            _stash(el, "role", _ROLE_MARKER_CO)
            _stash(el, "tabindex", _TABINDEX_MARKER_CO)
            el.name = "div"
            if not el.has_attr("role"):
                el["role"] = "button"
            if not el.has_attr("tabindex"):
                el["tabindex"] = "0"
        return str(soup)

    @staticmethod
    def revert(html: str, selector: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for el in _injected(soup, selector, _TAG_MARKER):
            el.name = el[_TAG_MARKER]
            del el[_TAG_MARKER]
            _restore(el, "role", _ROLE_MARKER_CO)
            _restore(el, "tabindex", _TABINDEX_MARKER_CO)
        return str(soup)


# --- strip_accessible_name -------------------------------------------------------

_CONTENT_MARKER = "data-verity-original-content-noname"
_NAME_ATTRS = ("aria-label", "aria-labelledby", "title")


class strip_accessible_name:  # noqa: N801
    """Remove every source of a control's accessible name: its content and naming attributes."""

    @staticmethod
    def inject(html: str, selector: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for el in soup.select(selector):
            if el.has_attr(_CONTENT_MARKER):
                continue
            el[_CONTENT_MARKER] = el.decode_contents()
            el.clear()
            for attr in _NAME_ATTRS:
                marker = f"data-verity-original-{attr}-noname"
                _stash(el, attr, marker)
                if el.has_attr(attr):
                    del el[attr]
        return str(soup)

    @staticmethod
    def revert(html: str, selector: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for el in _injected(soup, selector, _CONTENT_MARKER):
            original = BeautifulSoup(el[_CONTENT_MARKER], "html.parser")
            del el[_CONTENT_MARKER]
            el.clear()
            for child in list(original.contents):
                el.append(child)
            for attr in _NAME_ATTRS:
                _restore(el, attr, f"data-verity-original-{attr}-noname")
        return str(soup)


# --- invalid_aria_state ----------------------------------------------------------

class invalid_aria_state:  # noqa: N801
    """Give a state attribute a value assistive technology cannot interpret."""

    @staticmethod
    def inject(html: str, selector: str, attribute: str = "aria-expanded", value: str = "yes") -> str:
        return _set_attr(html, selector, attribute, value, f"data-verity-original-{attribute}-invalid")

    @staticmethod
    def revert(html: str, selector: str, attribute: str = "aria-expanded") -> str:
        return _unset_attr(html, selector, attribute, f"data-verity-original-{attribute}-invalid")


# --- dangling_idref --------------------------------------------------------------

class dangling_idref:  # noqa: N801
    """Point an id-reference attribute (aria-controls by default) at an id that does not exist."""

    @staticmethod
    def inject(html: str, selector: str, attribute: str = "aria-controls") -> str:
        return _set_attr(html, selector, attribute, MISSING_ID, f"data-verity-original-{attribute}-dangling")

    @staticmethod
    def revert(html: str, selector: str, attribute: str = "aria-controls") -> str:
        return _unset_attr(html, selector, attribute, f"data-verity-original-{attribute}-dangling")


# --- wrong_role ------------------------------------------------------------------

class wrong_role:  # noqa: N801
    """Replace an element's role with one the pattern does not allow there."""

    @staticmethod
    def inject(html: str, selector: str, role: str = "region") -> str:
        return _set_attr(html, selector, "role", role, "data-verity-original-role-wrongrole")

    @staticmethod
    def revert(html: str, selector: str) -> str:
        return _unset_attr(html, selector, "role", "data-verity-original-role-wrongrole")


# --- remove_from_tab_order -------------------------------------------------------

class remove_from_tab_order:  # noqa: N801
    """tabindex=-1 on every matched element — for a roving widget, on all its items."""

    @staticmethod
    def inject(html: str, selector: str) -> str:
        return _set_attr(html, selector, "tabindex", "-1", "data-verity-original-tabindex-untabbable")

    @staticmethod
    def revert(html: str, selector: str) -> str:
        return _unset_attr(html, selector, "tabindex", "data-verity-original-tabindex-untabbable")


INJECTORS = {
    "click_only_widget": click_only_widget,
    "strip_accessible_name": strip_accessible_name,
    "invalid_aria_state": invalid_aria_state,
    "dangling_idref": dangling_idref,
    "wrong_role": wrong_role,
    "remove_from_tab_order": remove_from_tab_order,
}
