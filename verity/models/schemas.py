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

# --- Contrast pixel sampling (A3.1–A3.4) ---
# Mirror of node-worker/static/sampling.ts::RegionSample. The Node side reads
# the real pixels behind a text element; this is the shape they cross the RPC
# boundary in, so the contrast adjudicator (verity/agents/contrast.py) consumes
# them typed. The model localises, the maths decides — nothing here is a ratio
# or a verdict.

class Rgb(BaseModel):
    r: int = Field(ge=0, le=255)
    g: int = Field(ge=0, le=255)
    b: int = Field(ge=0, le=255)


class BackgroundSample(Rgb):
    count: int = Field(ge=0)


class RegionSample(BaseModel):
    selector: str
    foreground: Rgb
    device_pixel_ratio: float
    background_samples: list[BackgroundSample] = []
    text_pixel_count: int = 0
    background_pixel_count: int = 0
    sampled: bool
    # When true the glyph/background split is unreliable (background coloured
    # near the text was swallowed into the text class). The adjudicator must
    # keep such a region needs_review, never pass it.
    ambiguous: bool = False


# --- Keyboard traversal (A4.1–A4.2 produce it, B4.1–B4.4 interpret it) ---
#
# PROPOSED CONTRACT — Track A has not built the traversal yet. This is written
# here first, deliberately: in Week 2 the `element_screenshots` shape was
# defined on the TS side and bolted into Python afterwards, the two drifted,
# and nothing caught it because no Python code validated a render payload.
# Defining it here gives Track A a target and gives Track B something to write
# real logic against today.
#
# Nothing in these models is a verdict. They describe *what happened when we
# pressed Tab* — the mapping to success criteria lives in agents/keyboard.py,
# on the Python side, where it can be unit-tested without a browser.

class UnreachedReason(str, Enum):
    """
    Why the traversal never landed on something it expected to.

    Three different kinds of thing live here, and conflating them is how a
    keyboard checker cries wolf:

    - a real barrier (`NOT_FOCUSABLE`, `OBSCURED`) — the user cannot get there
    - our own blind spot (`SHADOW_DOM`, `IFRAME`, `UNKNOWN`) — we did not look
    - correct authoring (`ARROW_NAVIGABLE`) — reachable, by a different key
    """
    SHADOW_DOM = "shadow-dom"
    IFRAME = "iframe"
    NOT_FOCUSABLE = "not-focusable"
    OBSCURED = "obscured"
    # Reached with arrow keys rather than Tab: the roving-tabindex pattern
    # used by tablist, menu, radiogroup, tree and grid. A tablist with six
    # tabs correctly exposes ONE tab stop; the other five carry tabindex=-1
    # by design. Reporting them as unreachable would fail Week 4's
    # zero-false-alarms gate on a widget that is built exactly right.
    ARROW_NAVIGABLE = "arrow-navigable"
    UNKNOWN = "unknown"


class TabStop(BaseModel):
    """One resting place of keyboard focus, in the order it was observed."""
    order: int = Field(ge=0, description="Position in the observed tab order.")
    selector: str
    cycle: int = Field(ge=0, description="Which full traversal cycle this stop belongs to.")
    bbox: Optional[BoundingBox] = None
    role: Optional[str] = None
    accessible_name: Optional[str] = None
    # The *authored* tabindex attribute, not the computed one. A positive
    # value is the signal SC 2.4.3 cares about: it lifts an element out of
    # DOM order and is the classic way focus order stops matching meaning.
    tabindex: Optional[int] = None
    # A4.3 fills this in. `None` means "not measured", which is different
    # from `False` ("measured, and there is no visible indicator") and must
    # never be collapsed into it.
    focus_visible: Optional[bool] = None
    dom_order: Optional[int] = Field(
        default=None,
        description="Position of this element in document order, for comparison with `order`.",
    )


class UnreachedRegion(BaseModel):
    """Something focusable that the traversal could not get to, and why."""
    selector: str
    reason: UnreachedReason
    detail: Optional[str] = None


class TraversalResult(BaseModel):
    """
    The outcome of pressing Tab repeatedly on one page state.

    `complete` is the honesty flag. A traversal that timed out, hit an
    unhandled shadow root, or lost focus to the browser chrome did not
    observe the page — it observed part of it. Interpreting a partial
    traversal as though it were whole is how a keyboard checker invents
    failures, so B4.2 turns `complete=False` into `indeterminate`.
    """
    stops: list[TabStop] = []
    cycles_requested: int = Field(ge=1)
    cycles_completed: int = Field(ge=0)
    returned_to_origin: bool = False
    # A4.2 owns the detection; assert only after N full cycles, N determined
    # by measurement. Track B only reads the verdict.
    trap_detected: bool = False
    trap_selector: Optional[str] = None
    unreached: list[UnreachedRegion] = []
    complete: bool
    incomplete_reason: Optional[str] = None
