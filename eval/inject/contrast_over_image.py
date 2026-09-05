"""
eval/inject/contrast_over_image.py — B3.4

Puts text over a background image so that axe-core cannot read the
background and marks the node `incomplete` rather than pass or fail.

This is the labelled data for Week 3's gate. `reduce_contrast` produces a
node axe can already judge; this one produces a node axe explicitly
*declines* to judge, which is the case the adjudicator exists to resolve.
Without it there is nothing to measure "beats axe-core recall" against.

The image is a 2x2 PNG inlined as a data URI, scaled to cover the element.
A data URI is used deliberately: no network fetch, no cross-origin taint,
and the fixture stays a single self-contained file. Its two dark and two
mid pixels stretch into a gradient-ish field, so a *worst-case* sample set
differs from an averaged one — which is the property `worst_case_ratio`
is supposed to catch.

Text colour is set to a mid grey. Against the darkest part of the image
this clears 3:1 but not 4.5:1 in some renderings, so the fixture also
exercises the "text size unknown" band rather than only the easy extremes.
"""

from bs4 import BeautifulSoup

# 2x2 PNG: two near-black pixels, two mid-grey. Base64 of a minimal PNG.
_BG_DATA_URI = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAF0lEQVQIHWNkYGD4z8DAwMTAwMDA"
    "wAAADgcBAV9lXOEAAAAASUVORK5CYII="
)

_OVER_IMAGE_STYLE = (
    f"background-image: url('{_BG_DATA_URI}') !important; "
    "background-size: cover !important; "
    "background-repeat: no-repeat !important; "
    "color: #7a7a7a !important;"
)

_MARKER = "data-verity-original-style-coi"
_NO_STYLE = "VERITY_NO_STYLE"


def inject(html_content: str, selector: str) -> str:
    """
    Place the matched elements' text over a background image.

    Uses its own marker attribute rather than sharing `reduce_contrast`'s.
    Both injectors touch the `style` attribute, and a shared marker would
    let one injector's revert silently undo the other's — which would show
    up as a corpus case that quietly lost its defect.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    for el in soup.select(selector):
        if el.has_attr("style"):
            el[_MARKER] = el.get("style", "")
            el["style"] = f"{el['style']}; {_OVER_IMAGE_STYLE}".strip("; ")
        else:
            el[_MARKER] = _NO_STYLE
            el["style"] = _OVER_IMAGE_STYLE

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
