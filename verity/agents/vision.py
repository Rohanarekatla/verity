"""
verity/agents/vision.py — Spike A vision judgments (B2.2, B2.3, B2.4).

Three judgments, one rule governing all of them: **the model may only report
what it can see, and must be able to say that it cannot see it.**

Constrained decoding guarantees well-formed output. It does not guarantee
true output — a required field with no supporting evidence in the image gets
filled anyway, fluently and confidently. That is the fabrication trap, and it
is why every schema below has a way out that the decoder can legally take,
and why the rubrics spend more words on when to answer `unknown` than on
anything else.

Nothing here computes a contrast ratio, and nothing here invents a
coordinate. The model localises; the maths decides.
"""

from typing import Callable, Literal, Optional, TYPE_CHECKING, TypeVar

from pydantic import BaseModel, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from verity.agents.vision_backends import VisionBackend


# ---------------------------------------------------------------------------
# B2.2 — Alt-text meaningfulness judge
# ---------------------------------------------------------------------------

ALT_TEXT_RUBRIC = """\
You are judging whether an image's alt text would be useful to someone who
cannot see the image. You can see the image; they cannot.

Answer `yes` only if the alt text conveys the information the image carries
in its context — what it depicts, or what it does if it is a control.

Answer `no` only if you can see a definite mismatch:
  - it describes something the image plainly does not show;
  - it is the filename, dimensions, or a placeholder ("image", "img_4023",
    "photo", "untitled", "DSC_0001");
  - it is redundant boilerplate that adds nothing ("image of", "picture of"
    and nothing else);
  - the image carries text or data that the alt text omits entirely.

Answer `unknown` in every other case. `unknown` is the correct, expected
answer — not a failure and not a last resort. Use it whenever:
  - the image is decorative and you cannot tell whether it is meant to be;
  - judging the alt text needs surrounding page context you were not given;
  - the image is too small, blurred, cropped, or ambiguous to identify;
  - the alt text may be accurate in a context you cannot see;
  - you would have to guess about the author's intent to answer.

Do not reason about whether the alt attribute exists — that is decided
deterministically before you are called. Judge only meaningfulness.

Your reasoning must cite what you actually see in the image. If you cannot
point to something visible that supports `yes` or `no`, the answer is
`unknown`.
"""


class AltTextJudgment(BaseModel):
    """
    Judge whether the provided alt text is meaningful for the given image.

    `unknown` is mandatory and load-bearing: an alt-text judgment forced to
    choose yes/no on an ambiguous image is a false positive generator, and
    precision is the metric Spike A is gated on.
    """

    meaningful: Literal["yes", "no", "unknown"] = Field(
        ...,
        description=(
            "Whether the alt text meaningfully describes the image. "
            "Must be 'unknown' if the image, its purpose, or the needed page "
            "context is not clear enough to decide."
        ),
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description=(
            "What you see in the image that supports this judgment. "
            "Cite visible evidence, not assumptions about intent."
        ),
    )


# ---------------------------------------------------------------------------
# B2.3 — Focus-visible judgment from before/after pairs
# ---------------------------------------------------------------------------

FOCUS_VISIBLE_RUBRIC = """\
You are shown two screenshots of the same element: `before`, with the element
unfocused, and `after`, with keyboard focus on it. Judge whether a sighted
keyboard user could tell, from the `after` image alone, which element has
focus.

Answer `yes` only if you can see a specific change that marks focus — an
outline, ring, border, background or colour shift, underline, or an added
indicator — and you could describe where it is.

Answer `no` only if you can see that the two images are equivalent in every
respect that would signal focus, and the element is plainly interactive.

Answer `unknown` whenever you are not certain the pair shows what it claims:
  - the two images differ in ways unrelated to focus (scroll position, an
    animation mid-flight, a hover state, loading content, a caret);
  - the change is present but so faint, thin, or low-contrast that you cannot
    tell whether it is an indicator or a rendering artefact;
  - either image is cut off, blurred, or does not clearly contain the
    element;
  - the indicator may fall outside the crop you were given.

`unknown` is the correct answer for an unclear pair. Do not resolve
uncertainty by picking the more likely option.

Do not judge whether the indicator meets a contrast threshold or a minimum
size — those are measured, not seen. Report only whether a change is visible.
"""


class FocusVisibleJudgment(BaseModel):
    """
    Judge whether a focus indicator is visible by comparing a before and
    after state.
    """

    focus_visible: Literal["yes", "no", "unknown"] = Field(
        ...,
        description=(
            "Whether a focus indicator is clearly visible in the 'after' "
            "state compared to the 'before' state. Must be 'unknown' if the "
            "pair differs for reasons unrelated to focus, or the change is "
            "too faint to call."
        ),
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description=(
            "The specific visible difference between the two images, and "
            "where it appears. Say so plainly if there is none."
        ),
    )


# ---------------------------------------------------------------------------
# B2.4 — Contrast-region localisation (bounding box only, never a ratio)
# ---------------------------------------------------------------------------

CONTRAST_LOCALISATION_RUBRIC = """\
You are shown a cropped screenshot of one element. Locate the text and the
background immediately behind it, as bounding boxes.

Return boxes in pixel coordinates relative to the top-left of the image you
were given, not the page.

Set `located` to `yes` and give both boxes only when you can see text in the
image and can place a box around it.

Set `located` to `unknown` and give no boxes at all when:
  - there is no legible text in the crop;
  - the text is cut off at an edge, so any box would be a guess;
  - the background behind the text is an image, gradient, video frame, or
    otherwise not a single region you can enclose;
  - the crop is blank, blurred, or you cannot tell text from decoration.

Returning no boxes is a valid, expected outcome and is always better than a
plausible-looking box you cannot actually see. A wrong box is worse than no
box: the contrast maths downstream trusts these coordinates completely and
will sample whatever pixels you point it at.

Do NOT report a contrast ratio, a colour, a hex value, or a pass/fail
judgment. You are not being asked whether the contrast is sufficient, and
there is no field in which to answer that question. Locate only.
"""


class VisionBoundingBox(BaseModel):
    """
    A box the model reported, in pixels relative to the crop it was shown.

    `ge=0` and `gt=0` are enforcement, not decoration: a negative origin or a
    zero-area box is a model that guessed, and it is cheaper to reject it here
    than to have the contrast sampler read an empty region and return a
    confident number about nothing.
    """

    x: float = Field(..., ge=0)
    y: float = Field(..., ge=0)
    width: float = Field(..., gt=0)
    height: float = Field(..., gt=0)


class ContrastRegionLocalisation(BaseModel):
    """
    Localise the foreground text and the background behind it.

    The model returns bounding boxes only, NEVER a contrast ratio — see
    `CONTRAST_LOCALISATION_RUBRIC`.

    `located` is the escape hatch. Without it, constrained decoding forces a
    box on every call, including calls where the crop contains no text at
    all, and the model has no legal way to decline. The boxes are optional
    and only permitted when `located == "yes"`.
    """

    located: Literal["yes", "unknown"] = Field(
        ...,
        description=(
            "'yes' only if text is visible and both regions can be enclosed. "
            "'unknown' if there is no legible text, it is cut off, or the "
            "background is not a single enclosable region. Omit both boxes "
            "when 'unknown'."
        ),
    )
    foreground_text_bbox: Optional[VisionBoundingBox] = Field(
        default=None,
        description=(
            "Bounding box of the foreground text, relative to the supplied "
            "crop. Do NOT compute a contrast ratio. Null when not located."
        ),
    )
    background_bbox: Optional[VisionBoundingBox] = Field(
        default=None,
        description=(
            "Bounding box of the background immediately behind the text, "
            "relative to the supplied crop. Null when not located."
        ),
    )

    @model_validator(mode="after")
    def _boxes_match_located(self) -> "ContrastRegionLocalisation":
        """
        Keep `located` and the boxes honest about each other.

        A model that answers `unknown` and then supplies coordinates anyway
        has fabricated them, and a model that answers `yes` with nothing to
        show has fabricated the `yes`. Both are the failure this schema
        exists to catch, so both are rejected rather than quietly normalised.
        """
        has_boxes = self.foreground_text_bbox is not None and self.background_bbox is not None
        if self.located == "yes" and not has_boxes:
            raise ValueError(
                "located='yes' requires both foreground_text_bbox and "
                "background_bbox"
            )
        if self.located == "unknown" and (
            self.foreground_text_bbox is not None or self.background_bbox is not None
        ):
            raise ValueError(
                "located='unknown' must not carry bounding boxes"
            )
        return self


# ---------------------------------------------------------------------------
# Agent surface
# ---------------------------------------------------------------------------

class VisionAgent:
    """
    Vision agent over a pluggable backend (see vision_backends.py).

    Each method passes its `*_RUBRIC` as the system prompt, sends the image(s),
    and validates the backend's JSON against the matching schema. The backend
    decides *where* the model runs — mlx-vlm on this Mac, a vLLM/Ollama server,
    or nothing at all — without changing a line here.

    The default backend abstains, so `VisionAgent()` with no model provisioned
    returns `unknown` for everything. That is deliberate: an un-wired agent
    contributes nothing to the precision measurement rather than inventing a
    confident default that would move Sunday's number unnoticed. And because
    validation failures also fall back to `unknown`, a model that emits
    malformed or off-schema output can never fabricate a judgment — abstention
    is the only way a call can go wrong.

    Provision a real backend with `VisionAgent.from_env()` plus the env vars
    documented in vision_backends.backend_from_env().
    """

    def __init__(self, backend: Optional["VisionBackend"] = None):
        # Imported lazily so importing the schemas never pulls in the backend
        # machinery, and so a checkout with no ML deps still loads cleanly.
        from verity.agents.vision_backends import AbstainBackend

        self.backend = backend if backend is not None else AbstainBackend()

    @classmethod
    def from_env(cls) -> "VisionAgent":
        from verity.agents.vision_backends import backend_from_env

        return cls(backend_from_env())

    def evaluate_alt_text(self, image_path: str, alt_text: str) -> AltTextJudgment:
        raw = self.backend.complete_json(
            system=ALT_TEXT_RUBRIC,
            user=(
                f"The alt text to judge is: {alt_text!r}\n\n"
                'Reply with a JSON object with exactly these keys:\n'
                '{"meaningful": "yes" | "no" | "unknown", '
                '"reasoning": "<what you see that supports this>"}'
            ),
            images=[image_path],
        )
        return _parse_or_abstain(
            raw,
            AltTextJudgment,
            lambda: AltTextJudgment(
                meaningful="unknown",
                reasoning="Vision backend unavailable or output invalid; abstaining.",
            ),
        )

    def evaluate_focus_visible(self, before_img: str, after_img: str) -> FocusVisibleJudgment:
        raw = self.backend.complete_json(
            system=FOCUS_VISIBLE_RUBRIC,
            user=(
                "Image 1 is `before` (unfocused); image 2 is `after` (focused).\n\n"
                'Reply with a JSON object with exactly these keys:\n'
                '{"focus_visible": "yes" | "no" | "unknown", '
                '"reasoning": "<the specific visible difference, or that there is none>"}'
            ),
            images=[before_img, after_img],
        )
        return _parse_or_abstain(
            raw,
            FocusVisibleJudgment,
            lambda: FocusVisibleJudgment(
                focus_visible="unknown",
                reasoning="Vision backend unavailable or output invalid; abstaining.",
            ),
        )

    def localise_contrast_regions(
        self, image_path: str, selector: str
    ) -> ContrastRegionLocalisation:
        raw = self.backend.complete_json(
            system=CONTRAST_LOCALISATION_RUBRIC,
            user=(
                f"Locate the text and its background in this crop of element {selector!r}.\n\n"
                'Reply with a JSON object. If you can see and place the text:\n'
                '{"located": "yes", '
                '"foreground_text_bbox": {"x": <n>, "y": <n>, "width": <n>, "height": <n>}, '
                '"background_bbox": {"x": <n>, "y": <n>, "width": <n>, "height": <n>}}\n'
                'If you cannot, give no boxes:\n{"located": "unknown"}'
            ),
            images=[image_path],
        )
        return _parse_or_abstain(
            raw,
            ContrastRegionLocalisation,
            lambda: ContrastRegionLocalisation(located="unknown"),
        )


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def _parse_or_abstain(
    raw: Optional[dict],
    schema: type[_ModelT],
    abstain: "Callable[[], _ModelT]",
) -> _ModelT:
    """
    Validate `raw` against `schema`, or return the abstaining answer.

    A missing object (backend down) and an off-schema object (model fabricated
    or hedged outside the allowed vocabulary) are the same outcome here:
    `unknown`. The schema is the last line of the fabrication defence, and
    validation failing is exactly the signal that the model could not answer
    honestly within it.
    """
    if raw is None:
        return abstain()
    try:
        return schema(**raw)
    except ValidationError:
        return abstain()
