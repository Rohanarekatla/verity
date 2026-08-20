"""Pure-logic tests for the Spike A measurement harness (no model, no render)."""

import json
from pathlib import Path

from eval.vision import measure


def test_wilson_interval_bounds_a_perfect_score_below_one():
    """20/20 is 100% point, but the lower bound must be below 1 — a small
    sample cannot prove near-certainty, which is why the bar is a lower bound."""
    point, lower, upper = measure.wilson_interval(20, 20)
    assert point == 1.0
    assert lower < 1.0
    assert lower > 0.8  # 20/20 still clears a fair amount of ground


def test_wilson_interval_zero_cases_is_zero_not_a_crash():
    assert measure.wilson_interval(0, 0) == (0.0, 0.0, 0.0)


def test_wilson_lower_bound_rises_with_sample_size():
    """The same 95% point estimate is more convincing with more samples."""
    _, lo_small, _ = measure.wilson_interval(19, 20)
    _, lo_large, _ = measure.wilson_interval(95, 100)
    assert lo_large > lo_small


def test_build_cases_makes_one_positive_and_n_negatives_per_image():
    spec = {
        "images": {
            "v-a": {"content": "x", "good_alt": "a real description"},
            "v-b": {"content": "y", "good_alt": "another description"},
        },
        "placeholder_alts": ["img.png", "image", "photo"],
    }
    crops = {"v-a": "/tmp/a.png", "v-b": "/tmp/b.png"}
    cases = measure.build_cases(crops, spec)

    # 2 images x (1 meaningful + 3 placeholder) = 8
    assert len(cases) == 8
    meaningful = [c for c in cases if c["meaningful"]]
    negatives = [c for c in cases if not c["meaningful"]]
    assert len(meaningful) == 2
    assert len(negatives) == 6
    assert {c["alt"] for c in negatives} == {"img.png", "image", "photo"}


def test_build_cases_skips_images_without_a_crop():
    spec = {
        "images": {"v-a": {"content": "x", "good_alt": "desc"}},
        "placeholder_alts": ["image"],
    }
    assert measure.build_cases({}, spec) == []


def test_cases_json_is_well_formed_and_negatives_are_placeholders():
    spec = json.loads((Path(measure.HERE) / "cases.json").read_text())
    assert spec["images"], "no images defined"
    for image_id, info in spec["images"].items():
        assert info["good_alt"].strip(), f"{image_id} has an empty good_alt"
    # placeholders must actually look like non-descriptions
    for ph in spec["placeholder_alts"]:
        assert ph in {"IMG_4023.jpg", "image", "photo"} or "." in ph or len(ph) <= 6
