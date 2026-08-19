"""
Tests for the Spike A vision schemas (B2.2, B2.3, B2.4).

These schemas exist to make fabrication structurally impossible, so the
tests are mostly about what the schema *refuses*. A schema that only accepts
well-formed honest answers is untested until something dishonest bounces off
it.
"""

import pytest
from pydantic import ValidationError

from verity.agents.vision import (
    ALT_TEXT_RUBRIC,
    CONTRAST_LOCALISATION_RUBRIC,
    FOCUS_VISIBLE_RUBRIC,
    AltTextJudgment,
    ContrastRegionLocalisation,
    FocusVisibleJudgment,
    VisionAgent,
    VisionBoundingBox,
)


# --- the escape hatch exists on every judgment ---

def test_every_judgment_can_abstain():
    """
    `unknown` must be reachable on all three judgments. This is the whole
    defence against the fabrication trap: a required field with no legal
    abstention is a field the model will fill with something.
    """
    assert AltTextJudgment(meaningful="unknown", reasoning="too small to read").meaningful == "unknown"
    assert FocusVisibleJudgment(focus_visible="unknown", reasoning="crop is cut off").focus_visible == "unknown"
    assert ContrastRegionLocalisation(located="unknown").located == "unknown"


def test_judgments_reject_values_outside_the_rubric():
    with pytest.raises(ValidationError):
        AltTextJudgment(meaningful="probably", reasoning="hedging")
    with pytest.raises(ValidationError):
        FocusVisibleJudgment(focus_visible="maybe", reasoning="hedging")
    with pytest.raises(ValidationError):
        ContrastRegionLocalisation(located="no")


def test_reasoning_cannot_be_empty():
    """An unsupported judgment is not a judgment."""
    with pytest.raises(ValidationError):
        AltTextJudgment(meaningful="no", reasoning="")
    with pytest.raises(ValidationError):
        FocusVisibleJudgment(focus_visible="yes", reasoning="")


# --- B2.4: bounding box only, and only when actually located ---

def test_contrast_localisation_never_carries_a_ratio():
    """
    There must be no field in which the model can report a contrast ratio,
    a colour, or a verdict. The model localises; the maths decides.
    """
    fields = set(ContrastRegionLocalisation.model_fields)
    assert fields == {"located", "foreground_text_bbox", "background_bbox"}

    # Extra keys are ignored by default, so assert the parsed object never
    # gains one even when the model volunteers it.
    parsed = ContrastRegionLocalisation.model_validate(
        {"located": "unknown", "contrast_ratio": 3.1, "passes": False}
    )
    assert not hasattr(parsed, "contrast_ratio")
    assert "contrast_ratio" not in parsed.model_dump()


def test_located_yes_requires_both_boxes():
    box = VisionBoundingBox(x=0, y=0, width=10, height=4)
    with pytest.raises(ValidationError, match="requires both"):
        ContrastRegionLocalisation(located="yes", foreground_text_bbox=box)
    with pytest.raises(ValidationError, match="requires both"):
        ContrastRegionLocalisation(located="yes")

    ok = ContrastRegionLocalisation(
        located="yes", foreground_text_bbox=box, background_bbox=box
    )
    assert ok.foreground_text_bbox is not None


def test_located_unknown_must_not_carry_boxes():
    """
    Abstaining and then supplying coordinates anyway is exactly the
    fabrication this schema is here to catch.
    """
    box = VisionBoundingBox(x=1, y=1, width=5, height=5)
    with pytest.raises(ValidationError, match="must not carry bounding boxes"):
        ContrastRegionLocalisation(
            located="unknown", foreground_text_bbox=box, background_bbox=box
        )


def test_bounding_box_rejects_impossible_geometry():
    """A zero-area or negative-origin box means the model guessed."""
    with pytest.raises(ValidationError):
        VisionBoundingBox(x=0, y=0, width=0, height=10)
    with pytest.raises(ValidationError):
        VisionBoundingBox(x=-1, y=0, width=10, height=10)
    with pytest.raises(ValidationError):
        VisionBoundingBox(x=0, y=0, width=10, height=-4)


# --- rubrics (B2.2, B2.3) ---

@pytest.mark.parametrize(
    "rubric",
    [ALT_TEXT_RUBRIC, FOCUS_VISIBLE_RUBRIC, CONTRAST_LOCALISATION_RUBRIC],
    ids=["alt_text", "focus_visible", "contrast_localisation"],
)
def test_each_judgment_has_a_rubric_that_teaches_abstention(rubric):
    """
    The plan asks for a judge *and a rubric*. A schema alone constrains the
    shape of an answer, not its honesty — the rubric is what tells the model
    when the answer is `unknown`.
    """
    assert rubric.strip()
    assert "unknown" in rubric


def test_contrast_rubric_forbids_ratio_reporting():
    assert "ratio" in CONTRAST_LOCALISATION_RUBRIC


# --- stub behaviour ---

def test_unwired_agent_abstains_rather_than_guessing():
    """
    Until Track A wires mlx-vlm in, every judgment must be `unknown`. A stub
    returning a confident default would quietly move Sunday's precision
    number.
    """
    agent = VisionAgent()
    assert agent.evaluate_alt_text("x.png", "logo").meaningful == "unknown"
    assert agent.evaluate_focus_visible("a.png", "b.png").focus_visible == "unknown"

    loc = agent.localise_contrast_regions("x.png", "#btn")
    assert loc.located == "unknown"
    assert loc.foreground_text_bbox is None
