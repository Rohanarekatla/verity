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
    """Represents element coordinates and size on screen in CSS pixels."""
    x: int
    y: int
    width: int
    height: int


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
    """Represents a single accessibility rule evaluation result."""
    id: str
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


class RenderArtifact(BaseModel):
    """Paths to assets captured by Developer A's browser worker."""
    page_state: PageState
    dom_path: str
    ax_tree_path: str
    styles_path: str
    screenshot_full: str
    element_screenshots: dict[str, str] = {}
    network_log_path: str


class AuditReport(BaseModel):
    """Final aggregated audit result output."""
    target: str
    standard: Literal["WCAG2.2-AA", "EN301549", "508", "INT"]
    findings: list[Finding]
    conformance: dict[str, str]
    verity_version: str
    ruleset_version: str