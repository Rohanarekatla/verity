"""Tests for dedup and waiver application (B6.1, B7.1/B7.2)."""

import textwrap

import pytest

from verity.agents.validator import (
    DEFAULT_WAIVERS_PATH,
    generate_finding_signature,
    load_waivers,
    process_findings,
    signature_for,
)
from verity.models.schemas import (
    Confidence,
    Evidence,
    Finding,
    Level,
    Modality,
    Provenance,
    Severity,
    SuccessCriterion,
)


def make_finding(
    rule_id: str = "color-contrast",
    selector: str = "#btn",
    sc_id: str = "1.4.3",
    finding_id: str | None = None,
) -> Finding:
    return Finding(
        id=finding_id or f"{rule_id}-abcdef123456",
        rule_id=rule_id,
        sc=SuccessCriterion(
            id=sc_id, name="Contrast (Minimum)", level=Level.AA, modality=Modality.DETERMINISTIC
        ),
        provenance=Provenance.AUTHORITATIVE,
        severity=Severity.SERIOUS,
        confidence=Confidence(score=1.0, method="deterministic"),
        agent="axe-core",
        outcome="fail",
        message="Insufficient contrast",
        evidence=Evidence(dom_selector=selector),
        page_state_hash="hash123",
    )


# --- signature ---

def test_signature_is_stable_across_processes():
    """
    sha256, not hash(): the signature is what a waiver written today must
    still match next month, in a different process.
    """
    assert generate_finding_signature("1.4.3", "#btn", "color-contrast") == (
        generate_finding_signature("1.4.3", "#btn", "color-contrast")
    )
    assert len(generate_finding_signature("1.4.3", "#btn", "color-contrast")) == 64


def test_signature_normalises_selector_whitespace():
    assert generate_finding_signature("1.4.3", "div  >   p", "x") == (
        generate_finding_signature("1.4.3", "div > p", "x")
    )


def test_signature_does_not_depend_on_finding_id_format():
    """
    The signature is built from `rule_id`, so changing how `Finding.id` is
    formatted must not invalidate existing waivers. Previously the rule was
    recovered by splitting the id, which coupled the two.
    """
    a = make_finding(finding_id="color-contrast-aaaa")
    b = make_finding(finding_id="color-contrast-9f2c1d4e5b6a")
    c = make_finding(finding_id="some-entirely-different-scheme")
    assert signature_for(a) == signature_for(b) == signature_for(c)


def test_signature_distinguishes_rule_selector_and_criterion():
    base = signature_for(make_finding())
    assert signature_for(make_finding(rule_id="image-alt")) != base
    assert signature_for(make_finding(selector="#other")) != base
    assert signature_for(make_finding(sc_id="1.1.1")) != base


# --- dedup ---

def test_duplicates_collapse_and_first_wins():
    first = make_finding()
    second = make_finding()
    second.message = "second occurrence"

    out = process_findings([first, second], waivers_path="does-not-exist.yaml")
    assert len(out) == 1
    assert out[0].message == "Insufficient contrast"


def test_distinct_findings_are_kept():
    out = process_findings(
        [make_finding(), make_finding(selector="#other"), make_finding(rule_id="image-alt", sc_id="1.1.1")],
        waivers_path="does-not-exist.yaml",
    )
    assert len(out) == 3


# --- waivers ---

def test_waiver_marks_finding_and_attaches_metadata(tmp_path):
    finding = make_finding()
    signature = signature_for(finding)

    waivers = tmp_path / "waivers.yaml"
    waivers.write_text(
        textwrap.dedent(
            f"""\
            partialFingerprints:
              "{signature}":
                justification: "Brand colours signed off."
                approved_by: "Design Lead"
                created: "2026-08-17"
                expires: "2027-08-17"
            """
        ),
        encoding="utf-8",
    )

    out = process_findings([finding], waivers_path=waivers)
    assert out[0].waived is True
    waiver = out[0].evidence.computed_values["waiver"]
    assert waiver["approved_by"] == "Design Lead"
    assert waiver["signature"] == signature


def test_unmatched_waiver_leaves_finding_unwaived(tmp_path):
    waivers = tmp_path / "waivers.yaml"
    waivers.write_text('partialFingerprints:\n  "' + "0" * 64 + '":\n    justification: "x"\n', encoding="utf-8")
    out = process_findings([make_finding()], waivers_path=waivers)
    assert out[0].waived is False


def test_missing_waivers_file_is_not_an_error(tmp_path):
    assert load_waivers(tmp_path / "nope.yaml") == {}


def test_repo_waivers_file_is_loadable_and_currently_empty():
    """
    The committed file previously held a placeholder fingerprint that matched
    no finding this engine can emit, so the waiver path had never run. Guard
    against a fingerprint being committed that nothing produced.
    """
    assert load_waivers() == {}


def test_waivers_path_is_repo_relative_not_cwd_relative(monkeypatch, tmp_path):
    """
    `verity scan` must behave identically from any directory. A cwd-relative
    waiver file silently stops applying when the CLI is run from elsewhere.
    """
    monkeypatch.chdir(tmp_path)
    assert DEFAULT_WAIVERS_PATH.is_absolute()
    assert DEFAULT_WAIVERS_PATH.exists()
    assert load_waivers() == {}


def test_malformed_waivers_file_is_rejected_loudly(tmp_path):
    waivers = tmp_path / "waivers.yaml"
    waivers.write_text("partialFingerprints:\n  - not-a-mapping\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_waivers(waivers)
