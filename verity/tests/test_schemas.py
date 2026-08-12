import pytest
from pydantic import ValidationError
from verity.models.schemas import (
    Level, Severity, Provenance, Modality,
    BoundingBox, SuccessCriterion, Evidence, Confidence,
    Finding, PageState, RenderArtifact, AuditReport
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