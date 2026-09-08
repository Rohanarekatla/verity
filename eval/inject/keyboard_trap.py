"""
eval/inject/keyboard_trap.py — B4.3

Traps keyboard focus on an element: Tab and Shift+Tab are swallowed, so
focus can enter but never leave. This is the canonical SC 2.1.2 failure and
the one Week 4's gate requires us to catch.

Implemented as an inline `onkeydown` handler rather than an attached
listener, because the injector's only tool is HTML text — there is no
JavaScript context to attach from, and an inline attribute survives the
BeautifulSoup round-trip that `revert` depends on.

Escape is deliberately *not* exempted. A trap you can escape from with a
key the user has to guess is still a trap under SC 2.1.2, which requires
that focus can be moved away using the keyboard alone with no special
knowledge.
"""

from bs4 import BeautifulSoup

_TRAP_HANDLER = (
    "if(event.key==='Tab'){event.preventDefault();event.stopPropagation();"
    "this.focus();}"
)

_MARKER = "data-verity-original-onkeydown-trap"
_NO_HANDLER = "VERITY_NO_ONKEYDOWN"


def inject(html_content: str, selector: str) -> str:
    """Swallow Tab on the matched elements so focus cannot leave them."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr("onkeydown"):
            el[_MARKER] = el.get("onkeydown", "")
            el["onkeydown"] = f"{el['onkeydown']}; {_TRAP_HANDLER}".strip("; ")
        else:
            el[_MARKER] = _NO_HANDLER
            el["onkeydown"] = _TRAP_HANDLER

        # An element that cannot receive focus cannot be trapped, so make
        # sure it can. Recorded separately for an exact revert.
        if not el.has_attr("tabindex"):
            el["data-verity-added-tabindex-trap"] = "1"
            el["tabindex"] = "0"

    return str(soup)


def revert(html_content: str, selector: str) -> str:
    """Undo `inject`, restoring the original handler exactly."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr(_MARKER):
            original = el.get(_MARKER, "")
            if original == _NO_HANDLER:
                del el["onkeydown"]
            else:
                el["onkeydown"] = original
            del el[_MARKER]

        if el.has_attr("data-verity-added-tabindex-trap"):
            del el["tabindex"]
            del el["data-verity-added-tabindex-trap"]

    return str(soup)
