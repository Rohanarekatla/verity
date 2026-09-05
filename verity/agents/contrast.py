"""
verity/agents/contrast.py — contrast maths and adjudication (B3.1–B3.3).

This is the first wedge: resolving findings axe-core explicitly declines to
judge, while keeping the result **authoritative**.

**There is no model in this path.** Pixels come from `sampleRegion` on the
Node side (A3.1–A3.4); the verdict is arithmetic from the WCAG 2.x spec.
The model localises, the maths decides — and here, nothing localises at all.

The governing constraint is Week 3's gate: beat axe-core's recall at **zero
new false positives**. Every branch below that cannot prove its answer
returns `cantTell`, not a guess.
"""

from typing import Iterable, Optional

from verity.models.schemas import (
    BackgroundSample,
    Confidence,
    Finding,
    Modality,
    Provenance,
    RegionSample,
    Rgb,
)

# WCAG 2.x SC 1.4.3 thresholds.
#
# 4.5:1 for normal text, 3:1 for large text (>= 18pt, or 14pt bold). Which
# one applies depends on the rendered font size and weight — and neither
# `RegionSample` nor `AxeNodeResult` carries them today.
#
# So we adjudicate only where the answer is the same under *both* thresholds:
#
#     ratio >= 4.5   passes whether the text is large or not   -> pass
#     ratio <  3.0   fails whether the text is large or not    -> fail
#     3.0 <= r < 4.5 depends on a font size we do not have     -> cantTell
#
# The middle band is not a gap in the maths, it is a gap in the input.
# Guessing 4.5 there would flag compliant large text as a failure, which is
# exactly the false positive the Sunday gate forbids. Widening the band is a
# matter of Track A adding fontSize/fontWeight, not of changing this rule.
THRESHOLD_NORMAL_TEXT = 4.5
THRESHOLD_LARGE_TEXT = 3.0


def _normalize_srgb(c: int) -> float:
    """
    Applies the sRGB curve adjustment.
    """
    c_norm = c / 255.0
    return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4


def calculate_relative_luminance(r: int, g: int, b: int) -> float:
    """
    Calculates the relative luminance of a color.
    """
    R = _normalize_srgb(r)
    G = _normalize_srgb(g)
    B = _normalize_srgb(b)

    return 0.2126 * R + 0.7152 * G + 0.0722 * B


def calculate_contrast_ratio(l1: float, l2: float) -> float:
    """
    Calculates the contrast ratio between two relative luminances.
    """
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def ratio_between(a: Rgb, b: Rgb) -> float:
    """Contrast ratio between two colours, straight from the spec."""
    return calculate_contrast_ratio(
        calculate_relative_luminance(a.r, a.g, a.b),
        calculate_relative_luminance(b.r, b.g, b.b),
    )


# --- B3.1: worst-case ratio over a set of background samples ---------------

def worst_case_ratio(
    foreground: Rgb, background_samples: Iterable[BackgroundSample]
) -> Optional[float]:
    """
    The **lowest** contrast ratio between the text colour and any sampled
    background colour.

    Worst-case, not average, and this is the whole point of A3.3 returning a
    per-region sample *set* rather than one averaged colour. Text sitting on
    a photograph or a gradient has many backgrounds; averaging them produces
    a colour that appears nowhere on screen and a ratio no reader ever
    experiences. White text over a sky that darkens to the horizon is
    legible at the top and invisible at the bottom, and the average says it
    is fine.

    A reader has to be able to read *every* glyph, so the region is only as
    good as its worst pixel.

    Returns None when there are no samples — the caller must treat that as
    undecidable, not as a pass.
    """
    ratios = [ratio_between(foreground, bg) for bg in background_samples]
    if not ratios:
        return None
    return min(ratios)


# --- B3.3: why a region could not be adjudicated ---------------------------

# Reason codes recorded on the finding when adjudication cannot reach a
# verdict. These exist so a `cantTell` is explainable rather than merely
# unresolved — a user who sees "we could not decide" is owed the reason.
REASON_NOT_SAMPLED = "sampling-failed"
REASON_AMBIGUOUS = "glyph-background-split-unreliable"
REASON_NO_BACKGROUND = "no-background-samples"
REASON_THRESHOLD_UNKNOWN = "text-size-unknown"


def _mark_inconclusive(finding: Finding, reason: str, detail: str) -> Finding:
    """
    B3.3 — an inconclusive region is reported, never resolved.

    `cantTell` + `NEEDS_REVIEW` is the honest outcome for animation, video,
    a cross-origin canvas, or any region where the pixels did not yield a
    defensible answer. It is not a failure and it must never gate a build;
    `cli.py` only exits non-zero on authoritative failures.
    """
    finding.provenance = Provenance.NEEDS_REVIEW
    finding.outcome = "cantTell"
    finding.confidence = Confidence(
        score=0.0,
        method="contrast-inconclusive",
        model=None,
        escape_used=False,
    )
    finding.sc.modality = Modality.PARTIAL
    finding.message = detail
    finding.evidence.computed_values["contrast_adjudication"] = {
        "resolved": False,
        "reason": reason,
    }
    return finding


def flag_needs_review(finding: Finding) -> Finding:
    """
    Incomplete contrast findings must start with NEEDS_REVIEW provenance
    and an outcome of cantTell until adjudicated.

    The confidence and modality are reset alongside them. They arrive from
    the mapper describing an authoritative axe violation — score 1.0, method
    "deterministic", modality DETERMINISTIC — and axe's `incomplete` bucket
    means precisely that axe could *not* decide. Leaving that metadata in
    place ships a `cantTell` finding claiming full deterministic confidence,
    and provenance is the one thing in this product that has to be exactly
    true.

    This remains the fallback for anything the adjudicator never saw — a
    node with no crop, a `sampleRegion` call that errored, a worker too old
    to support it.
    """
    finding.provenance = Provenance.NEEDS_REVIEW
    finding.outcome = "cantTell"
    finding.confidence = Confidence(
        score=0.0,
        method="axe-incomplete",
        model=None,
        escape_used=False,
    )
    finding.sc.modality = Modality.PARTIAL
    return finding


# --- B3.2: adjudication pipeline -------------------------------------------

def adjudicate_contrast(finding: Finding, sample: RegionSample) -> Finding:
    """
    Resolve one axe-`incomplete` contrast node from real pixels.

    axe marks a node `incomplete` when it cannot read the background —
    text over an image, a gradient, a canvas. It is not saying the contrast
    is bad; it is saying it does not know. Today that reaches the user as
    "needs review", which is honest but useless: the user still has to open
    a colour picker.

    This function does what axe declined to do, from the pixels that were
    actually rendered, and returns an **authoritative** verdict where the
    arithmetic is unambiguous.

    Outcomes:

    | Condition                        | outcome    | provenance    |
    |----------------------------------|------------|---------------|
    | sampling failed                  | cantTell   | NEEDS_REVIEW  |
    | glyph/background split ambiguous | cantTell   | NEEDS_REVIEW  |
    | no background samples            | cantTell   | NEEDS_REVIEW  |
    | worst ratio >= 4.5               | pass       | AUTHORITATIVE |
    | worst ratio <  3.0               | fail       | AUTHORITATIVE |
    | 3.0 <= worst ratio < 4.5         | cantTell   | NEEDS_REVIEW  |

    The last row is the zero-false-positive rule: in that band the verdict
    depends on whether the text is "large", and nothing in the pipeline
    knows that yet. See the threshold constants above.

    No model is consulted anywhere in this function.
    """
    if not sample.sampled:
        return _mark_inconclusive(
            finding,
            REASON_NOT_SAMPLED,
            "Contrast could not be adjudicated: the region's pixels could not "
            "be sampled (animation, video, or a cross-origin canvas).",
        )

    if sample.ambiguous:
        # A3.2's own warning. When the glyph/background split is unreliable,
        # background pixels have been counted as text — so the "foreground"
        # colour is not purely the text colour and any ratio computed from it
        # is measuring something that is not there.
        return _mark_inconclusive(
            finding,
            REASON_AMBIGUOUS,
            "Contrast could not be adjudicated: text and background pixels "
            "could not be separated reliably in this region.",
        )

    ratio = worst_case_ratio(sample.foreground, sample.background_samples)
    if ratio is None:
        return _mark_inconclusive(
            finding,
            REASON_NO_BACKGROUND,
            "Contrast could not be adjudicated: no background pixels were "
            "sampled behind the text.",
        )

    fg = sample.foreground
    evidence: dict = {
        "resolved": True,
        "worst_case_ratio": round(ratio, 4),
        "foreground_rgb": [fg.r, fg.g, fg.b],
        "background_samples_considered": len(sample.background_samples),
        "text_pixel_count": sample.text_pixel_count,
        "background_pixel_count": sample.background_pixel_count,
        "threshold_normal_text": THRESHOLD_NORMAL_TEXT,
        "threshold_large_text": THRESHOLD_LARGE_TEXT,
        "method": "worst-case over sampled background regions (WCAG 2.x)",
    }

    if ratio >= THRESHOLD_NORMAL_TEXT:
        finding.outcome = "pass"
        finding.provenance = Provenance.AUTHORITATIVE
        finding.message = (
            f"Contrast {ratio:.2f}:1 meets SC 1.4.3 at every sampled "
            f"background region, for text of any size."
        )
        evidence["verdict_basis"] = "above the 4.5:1 normal-text threshold"
    elif ratio < THRESHOLD_LARGE_TEXT:
        finding.outcome = "fail"
        finding.provenance = Provenance.AUTHORITATIVE
        finding.message = (
            f"Contrast {ratio:.2f}:1 fails SC 1.4.3 at its worst sampled "
            f"background region, for text of any size."
        )
        evidence["verdict_basis"] = "below the 3:1 large-text threshold"
    else:
        # The honest middle. Recorded with the ratio, because a reviewer with
        # the page in front of them can finish the job in seconds if we tell
        # them the number and what it hinges on.
        finding = _mark_inconclusive(
            finding,
            REASON_THRESHOLD_UNKNOWN,
            f"Contrast is {ratio:.2f}:1. This passes SC 1.4.3 for large text "
            f"(>= 3:1) but fails for normal text (>= 4.5:1), and the rendered "
            f"text size is not available. Needs review.",
        )
        evidence["resolved"] = False
        evidence["reason"] = REASON_THRESHOLD_UNKNOWN
        evidence["verdict_basis"] = "between the large-text and normal-text thresholds"
        finding.evidence.computed_values["contrast_adjudication"] = evidence
        return finding

    finding.confidence = Confidence(
        score=1.0,
        method="wcag-contrast-arithmetic",
        model=None,
        escape_used=False,
    )
    # The verdict came from real pixels, deterministically. That is exactly
    # what DETERMINISTIC means, and it is why this path may gate a build.
    finding.sc.modality = Modality.DETERMINISTIC
    finding.evidence.computed_values["contrast_adjudication"] = evidence
    return finding
