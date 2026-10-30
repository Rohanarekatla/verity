"""
eval/inject/common_defects.py — the WebAIM-common defects not already covered.

The injector set (A14.3) is weighted to the real web by prevalence
(`eval/inject/catalog.py`, WebAIM Million 2026). Most of the top defects already
have an injector — missing alt (`strip_alt`), low contrast (`reduce_contrast`),
missing form label (`detach_label`), empty link / empty button
(`aria_misuse.strip_accessible_name` scoped to `a[href]` / `button`). The one
top-six defect with no injector was **missing document language** (WCAG 3.1.1),
added here.

Same contract as the rest of the package: `inject(html, selector)` /
`revert(html, selector)`, reversible via a `data-verity-original-*` stash, HTML
text only.
"""

from __future__ import annotations

from bs4 import BeautifulSoup

_ABSENT = "VERITY_ABSENT"
_LANG_MARKER = "data-verity-original-lang-nolang"


def inject(html_content: str, selector: str = "html") -> str:
    """Remove the document's `lang` (and `xml:lang`) — SC 3.1.1. A screen
    reader then reads the page in the user's default voice, mispronouncing it."""
    soup = BeautifulSoup(html_content, "html.parser")
    for el in soup.select(selector):
        if el.has_attr(_LANG_MARKER):
            continue
        el[_LANG_MARKER] = el.get("lang", _ABSENT) if el.has_attr("lang") else _ABSENT
        for attr in ("lang", "xml:lang"):
            if el.has_attr(attr):
                del el[attr]
    return str(soup)


def revert(html_content: str, selector: str = "html") -> str:
    soup = BeautifulSoup(html_content, "html.parser")
    targets = list(soup.select(selector)) + [el for el in soup.select(f"[{_LANG_MARKER}]")]
    seen = set()
    for el in targets:
        if id(el) in seen or not el.has_attr(_LANG_MARKER):
            continue
        seen.add(id(el))
        original = el[_LANG_MARKER]
        del el[_LANG_MARKER]
        if original != _ABSENT:
            el["lang"] = original
    return str(soup)
