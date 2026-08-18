import time
from typing import Literal, Optional
from pydantic import BaseModel, Field

# B2.2: Alt-text meaningfulness judge
class AltTextJudgment(BaseModel):
    """
    Judge whether the provided alt text is meaningful for the given image.
    Mandatory 'unknown' option must be used if the model cannot determine it.
    """
    meaningful: Literal["yes", "no", "unknown"] = Field(
        ...,
        description="Whether the alt text meaningfully describes the image. Must be 'unknown' if unsure."
    )
    reasoning: str = Field(
        ...,
        description="Brief reasoning for the judgment according to the rubric."
    )

# B2.3: Focus-visible judgment
class FocusVisibleJudgment(BaseModel):
    """
    Judge whether a focus indicator is visible by comparing a before and after state.
    """
    focus_visible: Literal["yes", "no", "unknown"] = Field(
        ...,
        description="Whether the focus indicator is clearly visible in the 'after' state compared to the 'before' state."
    )
    reasoning: str = Field(
        ...,
        description="Brief reasoning for why the focus indicator is or is not visible."
    )

# B2.4: Contrast-region localisation
class VisionBoundingBox(BaseModel):
    x: int
    y: int
    width: int
    height: int

class ContrastRegionLocalisation(BaseModel):
    """
    Localise the foreground text and background region.
    The model must return a bounding box only, NEVER a contrast ratio.
    """
    foreground_text_bbox: VisionBoundingBox = Field(
        ...,
        description="Bounding box of the foreground text in CSS pixels. Do NOT compute contrast ratio."
    )
    background_bbox: VisionBoundingBox = Field(
        ...,
        description="Bounding box of the relevant background area immediately behind the text in CSS pixels."
    )

# Vision Model interface mock / stubs for now
class VisionAgent:
    def evaluate_alt_text(self, image_path: str, alt_text: str) -> AltTextJudgment:
        # TODO: wire up mlx-vlm call
        return AltTextJudgment(meaningful="unknown", reasoning="Not implemented yet.")
    
    def evaluate_focus_visible(self, before_img: str, after_img: str) -> FocusVisibleJudgment:
        # TODO: wire up mlx-vlm call
        return FocusVisibleJudgment(focus_visible="unknown", reasoning="Not implemented yet.")
    
    def localise_contrast_regions(self, image_path: str, selector: str) -> ContrastRegionLocalisation:
        # TODO: wire up mlx-vlm call
        return ContrastRegionLocalisation(
            foreground_text_bbox=VisionBoundingBox(x=0, y=0, width=0, height=0),
            background_bbox=VisionBoundingBox(x=0, y=0, width=0, height=0)
        )
