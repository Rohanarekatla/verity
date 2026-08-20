"""
Tests for the pluggable vision backends.

None of this needs a GPU or a model: a FakeBackend stands in for inference, so
the interesting logic — JSON extraction, schema validation, and the rule that
*any* failure becomes `unknown` — is tested deterministically. The real MLX and
OpenAI-compatible backends are exercised only for their fail-soft behaviour
(no deps / no server -> unavailable -> abstain), which is the property that
must hold on every machine.
"""

import pytest

from verity.agents.vision import VisionAgent
from verity.agents.vision_backends import (
    AbstainBackend,
    MLXBackend,
    OpenAICompatibleBackend,
    backend_from_env,
    extract_json_object,
)


class FakeBackend:
    """Returns a fixed object (or None) regardless of input."""

    def __init__(self, obj):
        self._obj = obj

    def available(self) -> bool:
        return self._obj is not None

    def complete_json(self, *, system, user, images):
        return self._obj


# --- JSON extraction ---

def test_extract_plain_object():
    assert extract_json_object('{"meaningful": "yes", "reasoning": "a dog"}') == {
        "meaningful": "yes",
        "reasoning": "a dog",
    }


def test_extract_from_markdown_fence_and_prose():
    text = 'Sure! Here is my answer:\n```json\n{"located": "unknown"}\n```\nHope that helps.'
    assert extract_json_object(text) == {"located": "unknown"}


def test_extract_ignores_braces_inside_strings():
    # A '}' inside a string value must not end the object early.
    assert extract_json_object('{"reasoning": "the alt is {broken}", "meaningful": "no"}') == {
        "reasoning": "the alt is {broken}",
        "meaningful": "no",
    }


def test_extract_returns_none_for_no_object():
    assert extract_json_object("I cannot answer that.") is None
    assert extract_json_object("") is None


def test_extract_returns_none_for_malformed_json():
    assert extract_json_object('{"meaningful": yes, no quotes}') is None


# --- the agent turns backend output into judgments, abstaining on anything wrong ---

def test_agent_uses_valid_backend_output():
    agent = VisionAgent(FakeBackend({"meaningful": "no", "reasoning": "filename as alt"}))
    result = agent.evaluate_alt_text("img.png", "IMG_4023.jpg")
    assert result.meaningful == "no"
    assert result.reasoning == "filename as alt"


def test_agent_abstains_when_backend_returns_nothing():
    agent = VisionAgent(FakeBackend(None))
    assert agent.evaluate_alt_text("img.png", "a cat").meaningful == "unknown"


def test_agent_abstains_on_off_schema_output():
    """A model that hedges outside the allowed vocabulary must not leak through."""
    agent = VisionAgent(FakeBackend({"meaningful": "probably", "reasoning": "hedging"}))
    assert agent.evaluate_alt_text("img.png", "a cat").meaningful == "unknown"


def test_agent_abstains_when_model_invents_a_box_it_should_not_have():
    """
    `located: unknown` with boxes violates the schema validator. The fabrication
    the schema exists to stop must resolve to abstention, not slip through.
    """
    agent = VisionAgent(
        FakeBackend({
            "located": "unknown",
            "foreground_text_bbox": {"x": 0, "y": 0, "width": 5, "height": 5},
        })
    )
    result = agent.localise_contrast_regions("crop.png", "#btn")
    assert result.located == "unknown"
    assert result.foreground_text_bbox is None


def test_agent_never_reports_a_contrast_ratio_even_if_the_model_tries():
    """There is no ratio field; a model that emits one has it dropped, not honoured."""
    agent = VisionAgent(
        FakeBackend({
            "located": "yes",
            "foreground_text_bbox": {"x": 1, "y": 1, "width": 10, "height": 4},
            "background_bbox": {"x": 0, "y": 0, "width": 20, "height": 8},
            "contrast_ratio": 2.1,  # not a field — must not survive
        })
    )
    result = agent.localise_contrast_regions("crop.png", "#btn")
    assert not hasattr(result, "contrast_ratio")
    assert result.located == "yes"


# --- backend selection and fail-soft ---

def test_abstain_backend_is_never_available():
    b = AbstainBackend()
    assert b.available() is False
    assert b.complete_json(system="s", user="u", images=[]) is None


def test_env_defaults_to_abstain(monkeypatch):
    monkeypatch.delenv("VERITY_VISION_BACKEND", raising=False)
    assert isinstance(backend_from_env(), AbstainBackend)


def test_env_openai_without_config_falls_back_to_abstain(monkeypatch):
    monkeypatch.setenv("VERITY_VISION_BACKEND", "openai")
    monkeypatch.delenv("VERITY_VISION_BASE_URL", raising=False)
    monkeypatch.delenv("VERITY_VISION_MODEL", raising=False)
    assert isinstance(backend_from_env(), AbstainBackend)


def test_env_openai_with_config_selects_openai_backend(monkeypatch):
    monkeypatch.setenv("VERITY_VISION_BACKEND", "openai")
    monkeypatch.setenv("VERITY_VISION_BASE_URL", "http://localhost:8000/v1")
    monkeypatch.setenv("VERITY_VISION_MODEL", "qwen2.5-vl")
    assert isinstance(backend_from_env(), OpenAICompatibleBackend)


def test_env_mlx_selects_mlx_backend(monkeypatch):
    monkeypatch.setenv("VERITY_VISION_BACKEND", "mlx")
    assert isinstance(backend_from_env(), MLXBackend)


def test_mlx_backend_is_unavailable_without_the_package():
    """On a machine without mlx-vlm, the backend reports unavailable and abstains
    rather than crashing the import or the scan."""
    b = MLXBackend("some/model")
    try:
        import mlx_vlm  # noqa: F401
        installed = True
    except ImportError:
        installed = False
    if not installed:
        assert b.available() is False
        assert b.complete_json(system="s", user="u", images=["x.png"]) is None


def test_openai_backend_abstains_when_endpoint_is_unreachable():
    b = OpenAICompatibleBackend(base_url="http://127.0.0.1:9/v1", model="x")
    # Port 9 (discard) refuses; the call must return None, not raise.
    assert b.complete_json(system="s", user="u", images=[]) is None
