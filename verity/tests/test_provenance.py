"""
Tests for B6.2 — provenance enforced at construction time.

Week 6's gate: **no path through the codebase produces a finding without an
explicit provenance value.** These tests go a step further and check that no
path produces one whose provenance contradicts its own evidence, because a
coherent-looking lie is worse than a missing field.
"""

import pytest
from pydantic import ValidationError

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

SC = SuccessCriterion(
    id="1.4.3", name="Contrast (Minimum)", level=Level.AA, modality=Modality.DETERMINISTIC
)


def build(**overrides) -> Finding:
    base = dict(
        id="color-contrast-abc123abc123",
        rule_id="color-contrast",
        sc=SC,
        provenance=Provenance.AUTHORITATIVE,
        severity=Severity.SERIOUS,
        confidence=Confidence(score=1.0, method="deterministic"),
        agent="axe-core",
        outcome="fail",
        message="Insufficient contrast",
        evidence=Evidence(dom_selector="#btn"),
        page_state_hash="hash123",
    )
    base.update(overrides)
    return Finding(**base)


# --- the gate itself -------------------------------------------------------

def test_provenance_has_no_default_and_cannot_be_omitted():
    """
    The gate, literally. A default would be a silent decision about whether a
    finding may fail someone's build.
    """
    fields = Finding.model_fields
    assert fields["provenance"].is_required()
    assert fields["provenance"].default is not None or fields["provenance"].is_required()

    with pytest.raises(ValidationError):
        Finding(
            id="x", rule_id="r", sc=SC, severity=Severity.MINOR,
            confidence=Confidence(score=1.0, method="m"), agent="a",
            outcome="fail", message="m", evidence=Evidence(),
            page_state_hash="h",
        )


def test_every_construction_site_in_the_codebase_sets_provenance_explicitly():
    """
    Greps the source rather than trusting memory. If a new `Finding(` appears
    without a provenance argument, this fails and names the file.

    `(?<!class )` excludes the declaration `class Finding(BaseModel)`, which
    is a definition rather than a construction — the first version of this
    test flagged it and was wrong.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    offenders = []
    scanned = 0
    for path in list((root / "verity").rglob("*.py")) + list((root / "eval").rglob("*.py")):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?<!class )\bFinding\(", text):
            scanned += 1
            call = text[match.end(): match.end() + 900].split("\n    )")[0]
            if "provenance=" not in call:
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(root)}:{line}")

    assert not offenders, f"Finding constructed without explicit provenance: {offenders}"
    # Guard against the guard: if the regex stops matching anything, this test
    # would pass vacuously while checking nothing.
    assert scanned >= 2, (
        f"expected to find the known construction sites in main.py and "
        f"keyboard.py, matched {scanned}"
    )


# --- coherence: AUTHORITATIVE ---------------------------------------------

def test_authoritative_cannot_be_canttell():
    """
    The exact contradiction shipped in the Week 2 report: outcome 'cantTell'
    sitting beside provenance 'authoritative'.
    """
    with pytest.raises(ValidationError, match="must be decided"):
        build(outcome="cantTell")


def test_authoritative_must_carry_full_confidence():
    with pytest.raises(ValidationError, match="confidence 1.0"):
        build(confidence=Confidence(score=0.8, method="deterministic"))


def test_authoritative_may_not_name_a_model():
    """A verdict a model helped produce is AI_ASSISTED, by definition."""
    with pytest.raises(ValidationError, match="AI_ASSISTED"):
        build(confidence=Confidence(score=1.0, method="vision", model="qwen-7b"))


@pytest.mark.parametrize("outcome", ["pass", "fail"])
def test_authoritative_accepts_decided_outcomes(outcome):
    assert build(outcome=outcome).outcome == outcome


# --- coherence: NEEDS_REVIEW ----------------------------------------------

def test_needs_review_must_be_canttell():
    with pytest.raises(ValidationError, match="outcome 'cantTell'"):
        build(
            provenance=Provenance.NEEDS_REVIEW,
            outcome="fail",
            confidence=Confidence(score=0.0, method="axe-incomplete"),
        )


def test_needs_review_may_not_claim_full_confidence():
    with pytest.raises(ValidationError, match="may not claim full confidence"):
        build(
            provenance=Provenance.NEEDS_REVIEW,
            outcome="cantTell",
            confidence=Confidence(score=1.0, method="axe-incomplete"),
        )


def test_needs_review_coherent_case_is_accepted():
    finding = build(
        provenance=Provenance.NEEDS_REVIEW,
        outcome="cantTell",
        confidence=Confidence(score=0.0, method="axe-incomplete"),
    )
    assert finding.provenance is Provenance.NEEDS_REVIEW


# --- coherence: AI_ASSISTED -----------------------------------------------

def test_ai_assisted_must_name_its_model():
    """
    Without the model name you cannot tell which findings to re-run when the
    model changes.
    """
    with pytest.raises(ValidationError, match="must name the model"):
        build(
            provenance=Provenance.AI_ASSISTED,
            confidence=Confidence(score=0.7, method="vision"),
        )

    ok = build(
        provenance=Provenance.AI_ASSISTED,
        confidence=Confidence(score=0.7, method="vision", model="qwen2.5-vl-7b-4bit"),
    )
    assert ok.confidence.model == "qwen2.5-vl-7b-4bit"


# --- mutation paths --------------------------------------------------------

def test_downgrade_paths_leave_a_coherent_finding():
    """
    The validator fires at construction, not assignment — the pipeline
    legitimately builds an authoritative finding then downgrades it, passing
    through a briefly incoherent state. What matters is that the *result*
    survives revalidation.
    """
    from verity.agents.contrast import flag_needs_review

    downgraded = flag_needs_review(build())
    assert downgraded.revalidate() is not None


def test_revalidate_catches_a_half_finished_mutation():
    """
    The loophole, made visible: flipping provenance without flipping outcome
    produces a finding that would never have been constructable.
    """
    finding = build()
    finding.provenance = Provenance.NEEDS_REVIEW  # outcome still "fail"

    with pytest.raises(ValidationError, match="outcome 'cantTell'"):
        finding.revalidate()


def test_adjudicated_contrast_findings_are_coherent():
    from verity.agents.contrast import adjudicate_contrast
    from verity.models.schemas import BackgroundSample, RegionSample, Rgb

    for bg, expected in [((0, 0, 0), "pass"), ((0x82, 0x82, 0x82), "fail")]:
        sample = RegionSample(
            selector="#btn",
            foreground=Rgb(r=255, g=255, b=255) if expected == "pass" else Rgb(r=0x80, g=0x80, b=0x80),
            device_pixel_ratio=2.0,
            background_samples=[BackgroundSample(r=bg[0], g=bg[1], b=bg[2], count=10)],
            sampled=True,
            ambiguous=False,
        )
        out = adjudicate_contrast(build(), sample)
        assert out.revalidate() is not None
        assert out.outcome == expected


def test_keyboard_findings_are_coherent():
    from verity.agents.keyboard import map_traversal_to_findings
    from verity.models.schemas import TabStop, TraversalResult

    result = TraversalResult(
        stops=[TabStop(order=0, selector="#a", cycle=0, tabindex=0, focus_visible=True)],
        cycles_requested=2, cycles_completed=2, returned_to_origin=True, complete=True,
    )
    for finding in map_traversal_to_findings(result, "hash"):
        assert finding.revalidate() is not None
