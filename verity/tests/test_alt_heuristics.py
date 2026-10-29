"""
A11.3 — deterministic alt-text heuristics and decorative detection.

The property that matters: the only `pass` verdicts are the author's own
decorative declarations; everything uncertain is `needs_review` (handed to the
model), never a silent pass. And the three-valued `alt` is kept apart —
absent (None) fails, explicit empty ("") is decorative.
"""

from verity.agents.alt_heuristics import (
    AltResult,
    accessible_name,
    judge_alt,
    judge_inventory,
    summarize,
)
from verity.models.schemas import BoundingBox, ImageInventory, ImageNode


def _img(**over) -> ImageNode:
    base = dict(
        selector="img#x", kind="img", tag="img",
        box_css=BoundingBox(x=0, y=0, width=200, height=150), visible=True,
    )
    base.update(over)
    return ImageNode(**base)


# --- definite failures (authoritative, no model) ---------------------------

def test_missing_alt_on_content_image_fails():
    r = judge_alt(_img(alt=None))
    assert r.outcome == "fail" and r.code == "alt-missing"


def test_alt_is_filename_fails():
    assert judge_alt(_img(alt="IMG_1234.jpg")).code == "alt-is-filename"
    assert judge_alt(_img(alt="photo.PNG")).code == "alt-is-filename"
    assert judge_alt(_img(alt="screenshot 2026-01-01")).code == "alt-is-filename"


def test_alt_is_placeholder_fails():
    assert judge_alt(_img(alt="image")).code == "alt-is-placeholder"
    assert judge_alt(_img(alt="  Photo ")).code == "alt-is-placeholder"
    assert judge_alt(_img(alt="spacer")).code == "alt-is-placeholder"


# --- correctly decorative (pass, no finding) -------------------------------

def test_empty_alt_is_decorative_pass():
    r = judge_alt(_img(alt=""))
    assert r.outcome == "pass" and r.decorative and r.code == "decorative-empty-alt"


def test_aria_hidden_is_decorative_pass():
    r = judge_alt(_img(alt=None, aria_hidden=True))
    assert r.outcome == "pass" and r.decorative


def test_role_presentation_is_decorative_pass():
    assert judge_alt(_img(alt=None, role="presentation")).decorative is True
    assert judge_alt(_img(alt=None, role="none")).decorative is True


def test_not_visible_is_not_flagged():
    assert judge_alt(_img(alt=None, visible=False)).outcome == "pass"


# --- deferred to the model (needs_review) ----------------------------------

def test_plausible_alt_is_deferred_not_passed():
    r = judge_alt(_img(alt="A golden retriever catching a frisbee"))
    assert r.outcome == "needs_review" and r.code == "alt-present"
    assert r.accessible_name == "A golden retriever catching a frisbee"


def test_logo_alt_is_not_a_placeholder():
    # "Acme logo" is a legitimate alt; it must not be failed as a placeholder.
    assert judge_alt(_img(alt="Acme logo")).outcome == "needs_review"


def test_aria_label_counts_as_a_name():
    r = judge_alt(_img(alt=None, aria_label="Submit the form"))
    assert r.outcome == "needs_review" and r.accessible_name == "Submit the form"


def test_icon_in_control_is_deferred_not_failed():
    r = judge_alt(_img(alt=None, in_control=True,
                       box_css=BoundingBox(x=0, y=0, width=20, height=20)))
    assert r.outcome == "needs_review" and r.code == "icon-in-control"


# --- the three-valued alt is kept apart ------------------------------------

def test_absent_and_empty_alt_are_different_outcomes():
    assert judge_alt(_img(alt=None)).outcome == "fail"   # absent → missing text alt
    assert judge_alt(_img(alt="")).outcome == "pass"      # explicit → decorative


def test_accessible_name_ignores_empty_alt():
    assert accessible_name(_img(alt="")) is None
    assert accessible_name(_img(alt="", aria_label="hi")) == "hi"
    assert accessible_name(_img(alt="a cat")) == "a cat"


# --- inventory + summary ---------------------------------------------------

def test_judge_inventory_and_summary():
    inv = ImageInventory(images=[
        _img(selector="#a", alt=None),            # fail
        _img(selector="#b", alt=""),              # pass (decorative)
        _img(selector="#c", alt="a real photo of a bridge"),  # needs_review
        _img(selector="#d", alt="IMG_9.png"),     # fail
    ])
    results = judge_inventory(inv)
    s = summarize(results)
    assert s["fail"] == 2 and s["pass"] == 1 and s["needs_review"] == 1


# --- schema-linter compliance (B11.2′) -------------------------------------

def test_alt_outcome_is_a_classified_judgment_with_an_escape():
    from verity.schema_lint import Judgment, lint_models

    # `outcome` is a judgment; its escape is `needs_review` (in ESCAPES).
    # `decorative` is NOT a judgment — it reports the author's own declaration.
    violations = lint_models(
        [AltResult],
        {"AltResult.outcome": Judgment()},
        {"AltResult.decorative": "reports the author's decorative declaration (aria-hidden / "
                                 "role=presentation / alt=''), not a verdict we reach"},
    )
    assert violations == [], f"alt heuristics output violates the escape rule: {violations}"
