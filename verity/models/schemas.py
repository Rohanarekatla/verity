from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel, Field

# 1. ENUMS (Allowed Choices)
class Level(str, Enum):
    A = "A"
    AA = "AA"
    AAA = "AAA"

class Severity(str, Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"

class Provenance(str, Enum):
    AUTHORITATIVE = "authoritative"
    AI_ASSISTED = "ai assisted"
    NEEDS_REVIEW = "needs review"

class Modality(str, Enum):
    DETERMINISTIC = "deterministic"
    PARTIAL = "partial"
    VISUAL = "visual"
    INTERACTION = "interaction"
    AUDIO = "audio"
    MANUAL = "manual"


# 2. SUPPORT MODELS
class BoundingBox(BaseModel):
    """
    A rectangle on the rendered page.

    Floats, not ints: `getBoundingClientRect()` returns subpixel values, and
    multiplying a CSS box by a fractional device-pixel ratio produces more of
    them. Rounding at the boundary would silently move every box by up to a
    pixel before the contrast math (Week 3) ever samples it.

    The coordinate system is *not* implied by this type — whoever holds a box
    must say which space it is in. See `ElementCapture`.
    """
    x: float
    y: float
    width: float
    height: float


class SuccessCriterion(BaseModel):
    """Represents a specific WCAG rule."""
    id: str
    name: str
    level: Level
    modality: Modality
    obsolete: bool = False
    act_rule_ids: list[str] = []
    techniques: list[str] = []


class Evidence(BaseModel):
    """Represents proof and context gathered for a finding."""
    dom_selector: Optional[str] = None
    ax_node_id: Optional[str] = None
    screenshot_path: Optional[str] = None
    region: Optional[BoundingBox] = None
    interaction_trace: Optional[list[str]] = None
    computed_values: dict = {}


class Confidence(BaseModel):
    """Represents engine confidence in a finding."""
    score: float = Field(ge=0.0, le=1.0)
    method: str
    model: Optional[str] = None
    escape_used: bool = False


#core models
class Finding(BaseModel):
    """
    Represents a single accessibility rule evaluation result.

    `rule_id` is the engine's own rule name (`color-contrast`, `image-alt`)
    and is carried verbatim. `id` is this finding's identity, derived from
    the rule and the selector. They are separate fields because the dedup
    signature needs the rule, and recovering it by string-surgery on `id`
    couples dedup to whatever format `id` happens to use this week.
    """
    id: str
    rule_id: str
    sc: SuccessCriterion
    provenance: Provenance
    severity: Severity
    confidence: Confidence
    agent: str
    engine: Optional[str] = None
    outcome: Literal["fail", "cantTell", "pass"]
    message: str
    remediation: Optional[str] = None
    evidence: Evidence
    page_state_hash: str
    waived: bool = False


class PageState(BaseModel):
    """Metadata representing the specific page context evaluated."""
    url: str
    state_label: str = "default"
    viewport: tuple[int, int]
    media_emulation: dict = {}
    content_hash: str


class ElementCapture(BaseModel):
    """
    One element-level screenshot (A2.1), with its box in both coordinate
    systems.

    This mirrors the `ElementCapture` interface in
    `node-worker/crawler/elements.ts` exactly. It is a cross-language
    contract: if the two drift, the Vision agent is handed coordinates that
    do not describe the PNG it is looking at.

    Both boxes are stored rather than one plus a multiplication, because
    re-deriving `box_device` from `box_css` at each consumer is how
    off-by-a-scale-factor bugs get in. `device_pixel_ratio` is recorded as
    measured, not assumed.
    """
    selector: str
    path: str
    box_css: BoundingBox
    box_device: BoundingBox
    device_pixel_ratio: float


class Latency(BaseModel):
    """
    Wall-clock cost of one page scan (B2.5).

    Week 2's second gate is a latency gate: if a page takes 90 s, "runs in
    CI" is quietly false. That gate needs a number in the report, not a line
    in a log that default logging levels discard.

    The phases are broken out because the descope decision differs by
    culprit — a slow render is Week 17's caching problem, slow analysis is
    not.
    """
    render_seconds: float
    analysis_seconds: float
    total_seconds: float


class RenderArtifact(BaseModel):
    """Paths to assets captured by Developer A's browser worker."""
    page_state: PageState
    dom_path: str
    ax_tree_path: str
    styles_path: str
    screenshot_full: str
    element_screenshots: dict[str, ElementCapture] = {}
    network_log_path: str


class AuditReport(BaseModel):
    """Final aggregated audit result output."""
    target: str
    standard: Literal["WCAG2.2-AA", "EN301549", "508", "INT"]
    findings: list[Finding]
    conformance: dict[str, str]
    verity_version: str
    ruleset_version: str
    latency: Optional[Latency] = None