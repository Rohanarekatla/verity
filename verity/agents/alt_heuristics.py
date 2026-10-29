"""
A11.3 — deterministic alt-text heuristics and decorative detection (SC 1.1.1).

The deterministic floor beneath the alt-text vision judgment (B-side,
`AltTextJudgment`). Its job is to resolve the cases a model is NOT needed for,
so the model only ever judges the genuinely ambiguous middle:

- **Definite failures** — authoritative, no model: a content image with the
  `alt` attribute *absent*; an `alt` that is a filename (`IMG_1234.jpg`); an
  `alt` that is a placeholder word (`"image"`, `"photo"`, `"spacer"`). None of
  these is a text alternative, and saying so needs no judgement.
- **Correctly decorative** — pass, no finding: `aria-hidden`,
  `role=presentation/none`, or an explicit empty `alt=""`. The author declared
  the image carries no information; we take the declaration at face value (a
  vision model may later second-guess a *meaningful* image hidden this way —
  that is the B-side's call, not ours).
- **Everything else** — `needs_review`: the image has a plausible alt, and
  whether it is *meaningful and accurate* is a model judgement, not a
  deterministic one. We decline rather than guess.

The `alt` field is three-valued and we keep it that way: `None` (attribute
absent) is a failure; `""` (explicit) is a decorative declaration; a non-empty
string is a candidate name. Collapsing absent into empty is how a missing-alt
failure gets silently excused.

This never *skips* a real failure into a pass: the only "pass" verdicts are the
author's own decorative declarations. When unsure, it returns `needs_review`,
not `pass`.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from verity.models.schemas import ImageInventory, ImageNode

# Three-state outcome. `needs_review` is the escape (hand to the model), so the
# closed vocabulary is honest — the schema linter's rule.
AltOutcome = Literal["pass", "fail", "needs_review"]

# An alt that is really a file name: ends in an image extension, or matches the
# camera/screenshot/export patterns authors paste in by accident.
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp|svg|tiff?|heic|avif)\s*$", re.I)
# `screenshot` optionally followed by a date/time (the OS auto-name), but not
# by prose: "screenshot 2026-01-01" is a file name, "screenshot of the login
# page" is a description and must not be failed.
_CAMERA = re.compile(r"^\s*(img[-_ ]?\d+|dsc[-_ ]?\d+|dcim|photo[-_ ]?\d+|"
                     r"screen[\s_-]?shot(?:[\s_-]+\d[\d\s:.at\-apm]*)?|"
                     r"untitled|image[-_ ]?\d+|p\d{6,}|[0-9a-f]{8,}|scan[-_ ]?\d+)\s*$", re.I)

# Placeholder alts: a word that names the medium, not the content. `logo` is
# deliberately NOT here — "Acme logo" is a legitimate alt for a logotype.
_PLACEHOLDERS = frozenset({
    "image", "images", "img", "photo", "photos", "picture", "pic", "graphic",
    "graphics", "icon", "spacer", "blank", "placeholder", "untitled", "thumbnail",
    "thumb", "banner", "figure", "alt", "alt text", "decorative",
})

# Icons this small inside a control are named by the control's text, not their
# own alt; a missing alt there is the control's problem (axe's button/link-name
# rule), so we defer rather than fail.
_ICON_MAX_PX = 48


class AltResult(BaseModel):
    selector: str
    outcome: AltOutcome
    # Machine-stable code plus a human reason.
    code: str
    detail: str
    # The accessible name we found (alt / aria-label / …), or None.
    accessible_name: Optional[str] = None
    # True when the author declared the image decorative (and we agree it is a
    # consistent declaration, not a finding).
    decorative: bool = False


def accessible_name(img: ImageNode) -> Optional[str]:
    """
    The image's accessible name from the attributes, or None.

    `alt=""` is NOT a name — it is a decorative declaration — so it does not
    count here. aria-label / aria-labelledby / title / figure caption do.
    """
    if img.alt:  # non-empty string only
        return img.alt.strip() or None
    for cand in (img.aria_label, img.aria_labelledby_text, img.title, img.figure_caption):
        if cand and cand.strip():
            return cand.strip()
    return None


def _declared_decorative(img: ImageNode) -> Optional[str]:
    """A reason the author declared this image decorative, or None."""
    if img.aria_hidden:
        return "aria-hidden"
    if (img.role or "").lower() in ("presentation", "none"):
        return f"role={img.role}"
    return None


def _looks_like_filename(name: str) -> bool:
    return bool(_IMAGE_EXT.search(name) or _CAMERA.match(name))


def _looks_like_placeholder(name: str) -> bool:
    return name.strip().lower() in _PLACEHOLDERS


def _is_icon_in_control(img: ImageNode) -> bool:
    return img.in_control and max(img.box_css.width, img.box_css.height) <= _ICON_MAX_PX


def judge_alt(img: ImageNode) -> AltResult:
    """Deterministically classify one image for SC 1.1.1."""

    def r(outcome: AltOutcome, code: str, detail: str, *, name=None, decorative=False) -> AltResult:
        return AltResult(selector=img.selector, outcome=outcome, code=code, detail=detail,
                         accessible_name=name, decorative=decorative)

    # Not rendered: nothing a user perceives, so no 1.1.1 finding either way.
    if not img.visible:
        return r("pass", "not-rendered", "image is not visible to a user")

    declared = _declared_decorative(img)
    name = accessible_name(img)

    # Author declared it decorative. We agree it is consistent and do not flag
    # it; a meaningful image wrongly hidden is a vision judgement (B-side).
    if declared:
        return r("pass", "decorative-declared", f"author declared decorative ({declared})", decorative=True)

    if name is not None:
        if _looks_like_filename(name):
            return r("fail", "alt-is-filename", f'alt is a file name, not a description: "{name[:60]}"', name=name)
        if _looks_like_placeholder(name):
            return r("fail", "alt-is-placeholder", f'alt is a placeholder word: "{name[:60]}"', name=name)
        # A plausible name exists. Whether it is meaningful/accurate is the
        # model's call, not ours — decline rather than pass or fail.
        return r("needs_review", "alt-present", "has a text alternative; meaningfulness is a model judgement", name=name)

    # No accessible name from here on.
    if img.alt == "":
        # Explicit empty alt with no other name: the author's decorative
        # declaration. Consistent; not a finding.
        return r("pass", "decorative-empty-alt", 'explicitly decorative (alt="")', decorative=True)

    # alt attribute is ABSENT (img.alt is None) and nothing else names it.
    if _is_icon_in_control(img):
        # A small icon inside a link/button is named by the control's text, if
        # any — a missing name there is the control's failure (button/link-name
        # rule), not this image's. Defer.
        return r("needs_review", "icon-in-control", "icon inside a control; its name comes from the control")

    if img.in_control:
        return r("needs_review", "image-in-control", "image inside a control; name may come from the control")

    # A visible content image with no text alternative at all. This is the
    # textbook SC 1.1.1 failure, and it needs no judgement.
    return r("fail", "alt-missing", "content image has no text alternative (alt attribute absent)")


def judge_inventory(inventory: ImageInventory) -> list[AltResult]:
    """Run the heuristics over every image in an A10.1 inventory."""
    return [judge_alt(img) for img in inventory.images]


def summarize(results: list[AltResult]) -> dict[str, int]:
    """Counts by outcome and code, for a quick read of what the floor resolved."""
    out: dict[str, int] = {"pass": 0, "fail": 0, "needs_review": 0}
    for res in results:
        out[res.outcome] += 1
        out[f"code:{res.code}"] = out.get(f"code:{res.code}", 0) + 1
    return out
