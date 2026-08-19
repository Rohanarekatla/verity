"""Tests for the contrast agent (B3.1, landed early)."""

import pytest

from verity.agents.contrast import (
    calculate_contrast_ratio,
    calculate_relative_luminance,
    flag_needs_review,
)
from verity.models.schemas import (
    Confidence,
    Evidence,
    Finding,
    Level,
    Modality,
    Provenance,
    Severity,
    SuccessCriterion,
)


# --- WCAG relative luminance and ratio, against values in the spec ---

def test_luminance_of_black_and_white():
    assert calculate_relative_luminance(0, 0, 0) == pytest.approx(0.0)
    assert calculate_relative_luminance(255, 255, 255) == pytest.approx(1.0)


def test_black_on_white_is_21_to_1():
    black = calculate_relative_luminance(0, 0, 0)
    white = calculate_relative_luminance(255, 255, 255)
    assert calculate_contrast_ratio(black, white) == pytest.approx(21.0, abs=1e-9)


def test_ratio_is_order_independent():
    a = calculate_relative_luminance(0x66, 0x66, 0x66)
    b = calculate_relative_luminance(255, 255, 255)
    assert calculate_contrast_ratio(a, b) == pytest.approx(calculate_contrast_ratio(b, a))


def test_identical_colours_are_1_to_1():
    grey = calculate_relative_luminance(0x80, 0x80, 0x80)
    assert calculate_contrast_ratio(grey, grey) == pytest.approx(1.0)


# --- incomplete → needs review ---

def _authoritative_finding() -> Finding:
    return Finding(
        id="color-contrast-abc123abc123",
        rule_id="color-contrast",
        sc=SuccessCriterion(
            id="1.4.3", name="Contrast (Minimum)", level=Level.AA, modality=Modality.DETERMINISTIC
        ),
        provenance=Provenance.AUTHORITATIVE,
        severity=Severity.SERIOUS,
        confidence=Confidence(score=1.0, method="deterministic"),
        agent="axe-core",
        outcome="fail",
        message="Insufficient contrast",
        evidence=Evidence(dom_selector="#btn"),
        page_state_hash="hash123",
    )


def test_flag_needs_review_sets_provenance_and_outcome():
    out = flag_needs_review(_authoritative_finding())
    assert out.provenance is Provenance.NEEDS_REVIEW
    assert out.outcome == "cantTell"


def test_flag_needs_review_clears_the_deterministic_metadata():
    """
    axe's `incomplete` bucket means axe could not decide. Shipping that as a
    `cantTell` still claiming score 1.0 / "deterministic" would make the
    provenance record untrue, which is the one thing this product cannot do.
    """
    out = flag_needs_review(_authoritative_finding())
    assert out.confidence.score == 0.0
    assert out.confidence.method == "axe-incomplete"
    assert out.confidence.model is None
    assert out.sc.modality is Modality.PARTIAL
