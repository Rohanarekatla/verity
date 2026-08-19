import pytest
from pydantic import ValidationError
from verity.models.schemas import (
    Level, Severity, Provenance, Modality,
    BoundingBox, SuccessCriterion, Evidence, Confidence,
    ElementCapture, Finding, Latency, PageState, RenderArtifact, AuditReport
)


# --- ENUM TESTS ---
def test_level_enum_validation():
    assert Level("A") == Level.A
    assert Level("AA") == Level.AA
    assert Level("AAA") == Level.AAA

    with pytest.raises(ValueError):
        Level("AAAA")


def test_severity_enum_validation():
    assert Severity("critical") == Severity.CRITICAL
    assert Severity("serious") == Severity.SERIOUS
    assert Severity("moderate") == Severity.MODERATE
    assert Severity("minor") == Severity.MINOR

    with pytest.raises(ValueError):
        Severity("super_bad")


def test_provenance_enum_validation():
    assert Provenance("authoritative") == Provenance.AUTHORITATIVE
    assert Provenance("ai assisted") == Provenance.AI_ASSISTED
    assert Provenance("needs review") == Provenance.NEEDS_REVIEW

    with pytest.raises(ValueError):
        Provenance("guess")


def test_modality_enum_validation():
    assert Modality("deterministic") == Modality.DETERMINISTIC
    assert Modality("partial") == Modality.PARTIAL
    assert Modality("visual") == Modality.VISUAL
    assert Modality("interaction") == Modality.INTERACTION
    assert Modality("audio") == Modality.AUDIO
    assert Modality("manual") == Modality.MANUAL

    with pytest.raises(ValueError):
        Modality("unknown_modality")


# --- SUPPORT MODEL TESTS ---
def test_confidence_score_validation():
    conf = Confidence(score=0.95, method="deterministic")
    assert conf.score == 0.95

    with pytest.raises(ValidationError):
        Confidence(score=1.5, method="deterministic")

    with pytest.raises(ValidationError):
        Confidence(score=-0.1, method="deterministic")


def test_bounding_box():
    box = BoundingBox(x=10, y=20, width=100, height=200)
    assert box.x == 10
    assert box.width == 100


def test_bounding_box_keeps_subpixels():
    """
    getBoundingClientRect() returns fractional values, and a CSS box times a
    fractional device-pixel ratio produces more of them. Ints silently
    rejected or rounded them.
    """
    box = BoundingBox(x=12.5, y=0.25, width=100.75, height=19.5)
    assert box.x == 12.5
    assert box.height == 19.5


# --- CROSS-LANGUAGE CONTRACT (A2.2) ---
def test_render_artifact_accepts_track_a_element_captures():
    """
    Track A's `element_screenshots` is Record<string, ElementCapture> — an
    object per selector with both coordinate systems and the measured device
    pixel ratio (node-worker/crawler/elements.ts). This model declared
    dict[str, str], so a real render payload would not have parsed. Nothing
    caught it because the orchestrator reads raw dicts and never validates a
    RenderArtifact; this test is that missing check.

    If this fails, elements.ts and schemas.py have drifted — fix both and
    re-run `python export_schema.py`.
    """
    payload = {
        "page_state": {
            "url": "https://example.com",
            "state_label": "default",
            "viewport": [1280, 720],
            "media_emulation": {},
            "content_hash": "abc123",
        },
        "dom_path": ".verity/cache/abc/dom.html",
        "ax_tree_path": ".verity/cache/abc/ax-tree.json",
        "styles_path": ".verity/cache/abc/styles.json",
        "screenshot_full": ".verity/cache/abc/page.png",
        "network_log_path": ".verity/cache/abc/network-log.json",
        "element_screenshots": {
            "#hero": {
                "selector": "#hero",
                "path": ".verity/cache/abc/elements/el-0123456789abcdef.png",
                "box_css": {"x": 12.5, "y": 40.0, "width": 300.25, "height": 150.5},
                "box_device": {"x": 25.0, "y": 80.0, "width": 600.5, "height": 301.0},
                "device_pixel_ratio": 2.0,
            }
        },
    }

    artifact = RenderArtifact.model_validate(payload)
    capture = artifact.element_screenshots["#hero"]
    assert isinstance(capture, ElementCapture)
    assert capture.device_pixel_ratio == 2.0
    # Both spaces are stored as measured, never re-derived by a consumer.
    assert capture.box_device.width == capture.box_css.width * capture.device_pixel_ratio


def test_element_capture_requires_both_coordinate_spaces():
    with pytest.raises(ValidationError):
        ElementCapture(
            selector="#hero",
            path="a.png",
            box_css=BoundingBox(x=0, y=0, width=10, height=10),
            device_pixel_ratio=2.0,
        )


# --- LATENCY (B2.5) ---
def test_audit_report_latency_is_optional_but_round_trips():
    latency = Latency(render_seconds=1.5, analysis_seconds=0.75, total_seconds=2.5)
    report = AuditReport(
        target="https://example.com",
        standard="WCAG2.2-AA",
        findings=[],
        conformance={},
        verity_version="0.1.0",
        ruleset_version="1.0.0",
        latency=latency,
    )
    assert AuditReport.model_validate_json(report.model_dump_json()).latency == latency


def test_success_criterion_defaults():
    sc = SuccessCriterion(
        id="1.4.3",
        name="Contrast (Minimum)",
        level=Level.AA,
        modality=Modality.DETERMINISTIC
    )
    assert sc.obsolete is False
    assert sc.act_rule_ids == []


# --- CORE MODEL ROUND-TRIP TESTS ---
def test_finding_mandatory_provenance():
    sc = SuccessCriterion(
        id="1.1.1", name="Non-text Content", level=Level.A, modality=Modality.DETERMINISTIC
    )
    confidence = Confidence(score=1.0, method="deterministic")
    evidence = Evidence(dom_selector="img#hero")

    # Missing provenance must raise ValidationError
    with pytest.raises(ValidationError):
        Finding(
            id="img-alt-001",
            rule_id="image-alt",
            sc=sc,
            severity=Severity.CRITICAL,
            confidence=confidence,
            agent="static",
            outcome="fail",
            message="Image missing alt text",
            evidence=evidence,
            page_state_hash="hash123"
        )


def test_finding_and_audit_report_json_roundtrip():
    sc = SuccessCriterion(
        id="1.4.3",
        name="Contrast (Minimum)",
        level=Level.AA,
        modality=Modality.DETERMINISTIC
    )
    confidence = Confidence(score=1.0, method="deterministic")
    evidence = Evidence(dom_selector="#submit", computed_values={"contrast": 2.1})

    finding = Finding(
        id="contrast-001",
        rule_id="color-contrast",
        sc=sc,
        provenance=Provenance.AUTHORITATIVE,
        severity=Severity.SERIOUS,
        confidence=confidence,
        agent="static",
        outcome="fail",
        message="Insufficient contrast ratio",
        evidence=evidence,
        page_state_hash="abc123hash"
    )

    report = AuditReport(
        target="https://example.com",
        standard="WCAG2.2-AA",
        findings=[finding],
        conformance={"1.4.3": "fail"},
        verity_version="0.1.0",
        ruleset_version="1.0.0"
    )

    # 1. Convert Python object -> JSON string
    json_str = report.model_dump_json()

    # 2. Convert JSON string -> Python object
    reconstructed = AuditReport.model_validate_json(json_str)

    # 3. Assert exact match
    assert reconstructed == report
    assert reconstructed.findings[0].provenance == Provenance.AUTHORITATIVE