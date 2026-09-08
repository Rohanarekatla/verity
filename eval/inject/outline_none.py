"""
eval/inject/outline_none.py — B4.3

Removes the focus indicator: `outline: none` with no replacement.

This is the SC 2.4.7 (Focus Visible) failure, and it is the single most
common accessibility bug on the web, usually introduced by a reset
stylesheet that nobody revisits. A sighted keyboard user tabbing through the
page has no idea where they are.

Two details worth knowing:

- `outline: none` is only a failure when nothing replaces it. A page that
  removes the outline and draws its own ring is compliant, which is exactly
  why SC 2.4.7 needs a *visual* check (A4.3's screenshot diff) rather than a
  CSS grep. This injector therefore removes the outline and adds nothing.
- `box-shadow: none` goes with it, since focus rings are frequently drawn
  that way, and leaving it would let a themed page keep an indicator this
  case is supposed to remove.
"""

from bs4 import BeautifulSoup

_NO_INDICATOR_STYLE = "outline: none !important; box-shadow: none !important;"

_MARKER = "data-verity-original-style-outline"
_NO_STYLE = "VERITY_NO_STYLE"


def inject(html_content: str, selector: str) -> str:
    """Strip the focus indicator from the matched elements."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr("style"):
            el[_MARKER] = el.get("style", "")
            el["style"] = f"{el['style']}; {_NO_INDICATOR_STYLE}".strip("; ")
        else:
            el[_MARKER] = _NO_STYLE
            el["style"] = _NO_INDICATOR_STYLE

    return str(soup)


def revert(html_content: str, selector: str) -> str:
    """Undo `inject`, restoring the original style attribute exactly."""
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr(_MARKER):
            original = el.get(_MARKER, "")
            if original == _NO_STYLE:
                del el["style"]
            else:
                el["style"] = original
            del el[_MARKER]

    return str(soup)
