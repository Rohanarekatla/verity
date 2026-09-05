"""
Tests for the contrast adjudicator (B3.1, B3.2, B3.3).

Week 3's gate is "beats axe-core recall at **zero new false positives**", so
most of these tests are about what the adjudicator *refuses* to decide. A
pipeline that resolves everything would score well on recall and fail the
gate outright.
"""

import pytest

from verity.agents.contrast import (
    REASON_AMBIGUOUS,
    REASON_NO_BACKGROUND,
    REASON_NOT_SAMPLED,
    REASON_THRESHOLD_UNKNOWN,
    THRESHOLD_LARGE_TEXT,
    THRESHOLD_NORMAL_TEXT,
    adjudicate_contrast,
    ratio_between,
    worst_case_ratio,
)
from verity.models.schemas import (
    BackgroundSample,
    Confidence,
    Evidence,
    Finding,
    Level,
    Modality,
    Provenance,
    RegionSample,
    Rgb,
    Severity,
    SuccessCriterion,
)

WHITE = Rgb(r=255, g=255, b=255)
BLACK = Rgb(r=0, g=0, b=0)


def make_incomplete_finding() -> Finding:
    """A color-contrast node as it arrives from the mapper, pre-adjudication."""
    return Finding(
        id="color-contrast-abc123abc123",
        rule_id="color-contrast",
        sc=SuccessCriterion(
            id="1.4.3",
            name="Contrast (Minimum)",
            level=Level.AA,
            modality=Modality.DETERMINISTIC,
        ),
        provenance=Provenance.AUTHORITATIVE,
        severity=Severity.SERIOUS,
        confidence=Confidence(score=1.0, method="deterministic"),
        agent="axe-core",
        outcome="fail",
        message="Insufficient contrast",
        evidence=Evidence(dom_selector="#text-over-image"),
        page_state_hash="hash123",
    )


def sample(
    foreground: Rgb = WHITE,
    backgrounds: list[tuple[int, int, int, int]] | None = None,
    sampled: bool = True,
    ambiguous: bool = False,
) -> RegionSample:
    bgs = [
        BackgroundSample(r=r, g=g, b=b, count=c)
        for (r, g, b, c) in (backgrounds if backgrounds is not None else [(0, 0, 0, 100)])
    ]
    return RegionSample(
        selector="#text-over-image",
        foreground=foreground,
        device_pixel_ratio=2.0,
        background_samples=bgs,
        text_pixel_count=500,
        background_pixel_count=2000,
        sampled=sampled,
        ambiguous=ambiguous,
    )


# --- B3.1: worst case, not average -----------------------------------------

def test_worst_case_is_the_minimum_ratio_not_the_average():
    """
    White text over a field that runs from black to near-white. The average
    background is mid-grey and looks acceptable; the light end is unreadable.
    A reader has to read every glyph, so the region is only as good as its
    worst pixel.
    """
    backgrounds = [
        BackgroundSample(r=0, g=0, b=0, count=500),        # 21:1  — fine
        BackgroundSample(r=240, g=240, b=240, count=500),  # ~1.1:1 — unreadable
    ]
    worst = worst_case_ratio(WHITE, backgrounds)

    assert worst == pytest.approx(ratio_between(WHITE, Rgb(r=240, g=240, b=240)))
    assert worst < 1.2
    # An averaging implementation would have landed near mid-grey and passed.
    average_bg = Rgb(r=120, g=120, b=120)
    assert ratio_between(WHITE, average_bg) > worst


def test_worst_case_with_no_samples_is_none_not_zero_and_not_a_pass():
    """None means undecidable. Returning 0.0 would read as a failure, and
    returning 21.0 would read as a pass — both would be inventions."""
    assert worst_case_ratio(WHITE, []) is None


def test_worst_case_single_sample_matches_the_direct_ratio():
    bgs = [BackgroundSample(r=0, g=0, b=0, count=10)]
    assert worst_case_ratio(WHITE, bgs) == pytest.approx(21.0)


# --- B3.2: authoritative verdicts where the maths is unambiguous ------------

def test_clear_pass_becomes_authoritative():
    """White on black is 21:1 — passes at any text size."""
    out = adjudicate_contrast(make_incomplete_finding(), sample(WHITE, [(0, 0, 0, 100)]))

    assert out.outcome == "pass"
    assert out.provenance is Provenance.AUTHORITATIVE
    assert out.confidence.score == 1.0
    assert out.confidence.method == "wcag-contrast-arithmetic"
    assert out.sc.modality is Modality.DETERMINISTIC

    adj = out.evidence.computed_values["contrast_adjudication"]
    assert adj["resolved"] is True
    assert adj["worst_case_ratio"] == pytest.approx(21.0, abs=0.01)


def test_clear_fail_becomes_authoritative():
    """#777777 on #808080 is about 1.1:1 — fails at any text size."""
    out = adjudicate_contrast(
        make_incomplete_finding(),
        sample(Rgb(r=0x77, g=0x77, b=0x77), [(0x80, 0x80, 0x80, 100)]),
    )

    assert out.outcome == "fail"
    assert out.provenance is Provenance.AUTHORITATIVE
    assert out.sc.modality is Modality.DETERMINISTIC
    assert out.evidence.computed_values["contrast_adjudication"]["resolved"] is True


def test_adjudication_beats_axe_on_a_case_axe_declined():
    """
    The point of the whole week: axe emitted this node as `incomplete` — no
    verdict at all. We turn it into an authoritative one.
    """
    before = make_incomplete_finding()
    after = adjudicate_contrast(before, sample(WHITE, [(0, 0, 0, 100)]))
    assert after.provenance is Provenance.AUTHORITATIVE
    assert after.outcome in {"pass", "fail"}


# --- B3.3 + the zero-false-positive rule ------------------------------------

def test_middle_band_is_cantTell_because_text_size_is_unknown():
    """
    The zero-false-positive rule. A ratio between 3:1 and 4.5:1 passes for
    large text and fails for normal text, and nothing in the pipeline knows
    which this is. Guessing 4.5 here would flag compliant large text as a
    failure — precisely the false positive the gate forbids.
    """
    # #858585 on white is ~3.69:1 — comfortably inside the band.
    out = adjudicate_contrast(
        make_incomplete_finding(), sample(Rgb(r=0x85, g=0x85, b=0x85), [(255, 255, 255, 100)])
    )
    adj = out.evidence.computed_values["contrast_adjudication"]
    ratio = adj["worst_case_ratio"]
    assert THRESHOLD_LARGE_TEXT <= ratio < THRESHOLD_NORMAL_TEXT

    assert out.outcome == "cantTell"
    assert out.provenance is Provenance.NEEDS_REVIEW
    assert adj["resolved"] is False
    assert adj["reason"] == REASON_THRESHOLD_UNKNOWN
    # The ratio is still reported — a reviewer with the page open can finish
    # the job in seconds if we tell them the number and what it hinges on.
    assert f"{ratio:.2f}" in out.message
    assert "large text" in out.message and "normal text" in out.message


def test_unsampled_region_is_cantTell():
    """Animation, video, cross-origin canvas — no pixels, no verdict."""
    out = adjudicate_contrast(make_incomplete_finding(), sample(sampled=False))
    assert out.outcome == "cantTell"
    assert out.provenance is Provenance.NEEDS_REVIEW
    assert out.evidence.computed_values["contrast_adjudication"]["reason"] == REASON_NOT_SAMPLED


def test_ambiguous_split_is_cantTell_even_when_the_ratio_looks_terrible():
    """
    A3.2 flags `ambiguous` when background pixels were counted as text. The
    'foreground' colour is then not the text colour, so any ratio computed
    from it measures something that isn't there — however damning it looks.
    """
    out = adjudicate_contrast(
        make_incomplete_finding(),
        sample(Rgb(r=0x80, g=0x80, b=0x80), [(0x82, 0x82, 0x82, 100)], ambiguous=True),
    )
    assert out.outcome == "cantTell"
    assert out.provenance is Provenance.NEEDS_REVIEW
    assert out.evidence.computed_values["contrast_adjudication"]["reason"] == REASON_AMBIGUOUS


def test_no_background_samples_is_cantTell_not_a_pass():
    out = adjudicate_contrast(make_incomplete_finding(), sample(backgrounds=[]))
    assert out.outcome == "cantTell"
    assert out.provenance is Provenance.NEEDS_REVIEW
    assert out.evidence.computed_values["contrast_adjudication"]["reason"] == REASON_NO_BACKGROUND


@pytest.mark.parametrize(
    "sample_kwargs",
    [
        {"sampled": False},
        {"ambiguous": True},
        {"backgrounds": []},
    ],
    ids=["not_sampled", "ambiguous", "no_background"],
)
def test_no_inconclusive_path_ever_produces_a_gating_finding(sample_kwargs):
    """
    `cli.py` exits non-zero only on authoritative failures. No inconclusive
    branch may ever reach that state, or an unknown becomes a broken build.
    """
    out = adjudicate_contrast(make_incomplete_finding(), sample(**sample_kwargs))
    assert not (out.provenance is Provenance.AUTHORITATIVE and out.outcome == "fail")
    assert out.confidence.score == 0.0


def test_outcome_always_matches_the_documented_rule_across_every_grey():
    """
    Property test over all 256 greys on white. For every one, the outcome must
    follow from the ratio by the documented rule — no colour anywhere in the
    space may slip into a verdict it hasn't earned.
    """
    assert THRESHOLD_NORMAL_TEXT == 4.5
    assert THRESHOLD_LARGE_TEXT == 3.0

    for v in range(256):
        grey = Rgb(r=v, g=v, b=v)
        # Use the unrounded ratio the adjudicator actually branches on, not
        # the rounded copy it records — otherwise a value like 4.49998 would
        # round to 4.5 and make this test disagree with correct behaviour.
        ratio = ratio_between(grey, Rgb(r=255, g=255, b=255))
        out = adjudicate_contrast(
            make_incomplete_finding(),
            sample(grey, [(255, 255, 255, 100)]),
        )

        if ratio >= THRESHOLD_NORMAL_TEXT:
            assert out.outcome == "pass" and out.provenance is Provenance.AUTHORITATIVE, v
        elif ratio < THRESHOLD_LARGE_TEXT:
            assert out.outcome == "fail" and out.provenance is Provenance.AUTHORITATIVE, v
        else:
            assert out.outcome == "cantTell" and out.provenance is Provenance.NEEDS_REVIEW, v


# --- no model in this path --------------------------------------------------

def test_adjudication_never_consults_a_model():
    """
    B3.2 says it explicitly: no model in this path. The finding must carry no
    model attribution, and `escape_used` (a vision concept) stays false.
    """
    out = adjudicate_contrast(make_incomplete_finding(), sample(WHITE, [(0, 0, 0, 100)]))
    assert out.confidence.model is None
    assert out.confidence.escape_used is False
    assert "model" not in out.confidence.method
