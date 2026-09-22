"""
eval/inject/positive_tabindex.py — B4.3

Gives an element a positive `tabindex`, lifting it out of document order.

This is the SC 2.4.3 (Focus Order) failure our checker is willing to assert.
Any positive value jumps the element to the front of the tab sequence
regardless of where it sits on the page, so a user tabbing through the
document meets it before everything above it. `tabindex="0"` and
`tabindex="-1"` are both legitimate and are *not* what this injects.

A high number is used rather than 1 so the disruption is unmistakable in a
recorded tab order, and so the case does not accidentally coincide with a
pre-existing `tabindex="1"` on a page that already had one.
"""

from bs4 import BeautifulSoup

_POSITIVE_VALUE = "99"
_MARKER = "data-verity-original-tabindex-pos"
_NO_TABINDEX = "VERITY_NO_TABINDEX"


def inject(html_content: str, selector: str) -> str:
    """Set a positive tabindex on the matched elements."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr("tabindex"):
            el[_MARKER] = el.get("tabindex", "")
        else:
            el[_MARKER] = _NO_TABINDEX
        el["tabindex"] = _POSITIVE_VALUE

    return str(soup)


def revert(html_content: str, selector: str) -> str:
    """Undo `inject`, restoring the original tabindex exactly."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr(_MARKER):
            original = el.get(_MARKER, "")
            if original == _NO_TABINDEX:
                del el["tabindex"]
            else:
                el["tabindex"] = original
            del el[_MARKER]

    return str(soup)
