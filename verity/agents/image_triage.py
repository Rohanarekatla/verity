"""
verity/agents/image_triage.py — A10.3: decide which images are worth OCR.

OCR for SC 1.4.5 (Images of Text) is the expensive stage of the vision
pipeline. Most images on a real page cannot contain an image of text that
1.4.5 cares about, and this module says which, with a recorded reason for
every image it drops — so a reviewer can see why something was not checked,
and a wrong rule can be found and fixed rather than guessed at.

The rules only ever SKIP work. Skipping costs recall on 1.4.5, never a false
finding: an image that is not OCR'd produces no verdict at all. So when a rule
is unsure, the image stays a candidate.

    decorative   alt="", role=presentation/none, or aria-hidden — the author
                 declared it carries no information, and decoration is exempt
    logo         logotypes are exempt from 1.4.5 ("essential")
    icon         icon-sized; named by its control, too small for running text
    not-text     text drawn as vector text (inline SVG) or real HTML text over
                 a background — not an image of text, and cropping it would OCR
                 the HTML text and invent a finding
    hidden / tiny  nothing a sighted user can read
    content      everything else — the OCR candidates

Identical images (same source, same rendered size) are OCR'd once.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel

from verity.models.schemas import ImageInventory, ImageNode

Category = Literal["hidden", "tiny", "decorative", "logo", "icon", "not-text", "content"]

# Below these, no running text a user could read fits (WCAG's minimum legible
# text is ~9 px tall; a word needs width).
MIN_TEXT_HEIGHT_PX = 12
MIN_TEXT_WIDTH_PX = 24
# Square-ish and at most this big, inside a control or a landmark: an icon.
ICON_MAX_PX = 48
_LOGO = re.compile(r"(^|[^a-z])logo(type|mark)?([^a-z]|$)", re.I)
# A text alternative that NAMES the image as a logo ("Stripe logo", "Acme
# logotype") — short, one phrase, ending in the word. One that DESCRIBES a
# scene containing a logo ("Apple Card, front, Apple logo in top left") is a
# content image, and on apple.com / stripe.com that over-match skipped photos.
_NAMED_LOGO = re.compile(r"^\s*[^,.;:]{0,40}?\blogo(type|mark)?\s*$", re.I)


class TriageResult(BaseModel):
    selector: str
    category: Category
    ocr_candidate: bool
    reasons: list[str]
    # Images sharing this key render the same pixels; OCR one, apply to all.
    dedup_key: Optional[str] = None


class TriageSummary(BaseModel):
    total: int
    candidates: int
    distinct_candidates: int
    by_category: dict[str, int]
    results: list[TriageResult]


def _is_logo(img: ImageNode) -> Optional[str]:
    for label, text in (("alt", img.alt), ("aria-label", img.aria_label)):
        if text and _NAMED_LOGO.search(text):
            return f'{label} names it a logo ("{text[:40]}")'
    if img.id_class_text and _LOGO.search(img.id_class_text):
        return f'id/class names a logo ("{img.id_class_text[:40]}")'
    for src in img.sources:
        name = src.rsplit("/", 1)[-1].split("?", 1)[0]
        if _LOGO.search(name):
            return f"source file is named as a logo ({name[:40]})"
    if img.in_landmark in ("header", "banner") and img.link_href in ("/", "./", "#", "index.html"):
        return "inside the page header, linking to the home page"
    return None


def classify(img: ImageNode) -> TriageResult:
    def result(category: Category, *reasons: str) -> TriageResult:
        return TriageResult(selector=img.selector, category=category, ocr_candidate=category == "content",
                            reasons=list(reasons) or ["no rule excluded it"])

    w, h = img.box_css.width, img.box_css.height
    if not img.visible:
        return result("hidden", "not rendered (display/visibility/opacity/zero size)")
    if h < MIN_TEXT_HEIGHT_PX or w < MIN_TEXT_WIDTH_PX:
        return result("tiny", f"{w:.0f}x{h:.0f} px is too small to hold readable text")
    if img.alt == "":
        return result("decorative", 'alt="" — the author marked it decorative')
    if img.role in ("presentation", "none"):
        return result("decorative", f'role="{img.role}" — the author marked it decorative')
    if img.aria_hidden:
        return result("decorative", "inside aria-hidden — hidden from assistive technology")
    logo = _is_logo(img)
    if logo:
        return result("logo", logo, "logotypes are exempt from SC 1.4.5")
    if max(w, h) <= ICON_MAX_PX and 0.5 <= w / h <= 2 and (img.in_control or img.in_landmark):
        return result("icon", f"{w:.0f}x{h:.0f} px inside a control or landmark — an icon")
    if img.kind == "svg":
        return result("not-text", "inline SVG: its text, if any, is vector text in the DOM, not an image of text")
    if img.kind == "css-background" and img.has_text_content:
        return result("not-text", "background behind real HTML text — a crop would OCR that text; "
                                  "contrast over it is the contrast adjudicator's job")
    r = result("content")
    r.dedup_key = f"{'|'.join(img.sources) or img.selector}@{round(w)}x{round(h)}"
    return r


def triage(inventory: ImageInventory) -> TriageSummary:
    results = [classify(i) for i in inventory.images]
    by_category: dict[str, int] = {}
    for r in results:
        by_category[r.category] = by_category.get(r.category, 0) + 1
    candidates = [r for r in results if r.ocr_candidate]
    return TriageSummary(
        total=len(results),
        candidates=len(candidates),
        distinct_candidates=len({r.dedup_key for r in candidates}),
        by_category=by_category,
        results=results,
    )


async def inventory_and_triage(rpc_call, artifact_id: str, capture: bool = True) -> dict:
    """
    Inventory the live page's images, triage them, and (optionally) crop one
    representative of each distinct candidate into the content-addressed store
    — the input B10.2's OCR runs on.
    """
    inventory = ImageInventory.model_validate(await rpc_call("inventoryImages", {"artifactId": artifact_id}))
    summary = triage(inventory)
    out = {"inventory": inventory, "triage": summary, "captures": {}, "distinct_files": 0}
    if capture:
        reps: dict[str, str] = {}
        for r in summary.results:
            if r.ocr_candidate and r.dedup_key not in reps:
                reps[r.dedup_key] = r.selector
        if reps:
            got = await rpc_call("captureImages", {"artifactId": artifact_id, "selectors": list(reps.values())})
            out["captures"], out["distinct_files"] = got["captures"], got["distinct_files"]
    return out
