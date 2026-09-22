"""
Tests for B6.3 (severity policy) and B6.4 (validator as a versioned,
browser-free module).

Severity answers "how badly is a user blocked?" — not "how sure are we"
(confidence) and not "who decided" (provenance). Most of these tests are
about keeping those three apart, because conflating them produces a report
where everything is critical and nobody triages anything.
"""

import pytest

from verity.agents.validator import (
    VALIDATOR_VERSION,
    assign_severity,
    explain_severity,
)
from verity.models.schemas import Level, Provenance, Severity

AUTH = Provenance.AUTHORITATIVE
REVIEW = Provenance.NEEDS_REVIEW


# --- blocking criteria -----------------------------------------------------

def test_level_a_blocking_failure_is_critical():
    """
    Level A is the floor of the standard. A blocking failure of the floor is
    the worst thing this tool can report.
    """
    assert assign_severity("2.1.1", Level.A, "fail", AUTH) is Severity.CRITICAL
    assert assign_severity("2.1.2", Level.A, "fail", AUTH) is Severity.CRITICAL


def test_blocking_floor_beats_a_low_engine_rating():
    """axe rates the rule; we rate this instance. The floor wins."""
    assert assign_severity("1.1.1", Level.A, "fail", AUTH, "minor") is Severity.CRITICAL


def test_level_aa_blocking_failure_is_serious_not_critical():
    assert assign_severity("2.4.7", Level.AA, "fail", AUTH) is Severity.SERIOUS


# --- the two ceilings ------------------------------------------------------

def test_undecided_findings_are_capped_at_moderate():
    """
    The important one. Labelling a maybe as `critical` teaches the reader
    that `critical` does not mean critical — and then the real ones get
    ignored too.
    """
    assert assign_severity("2.1.1", Level.A, "cantTell", REVIEW) is Severity.MODERATE
    assert assign_severity("1.4.3", Level.AA, "cantTell", REVIEW, "serious") is Severity.MODERATE


def test_non_authoritative_findings_are_capped_even_when_decided():
    """A model-assisted finding may not claim the top of the scale."""
    capped = assign_severity(
        "2.1.1", Level.A, "fail", Provenance.AI_ASSISTED, "critical"
    )
    assert capped is Severity.MODERATE


def test_a_pass_is_always_minor():
    """Severity describes a defect; a pass has none."""
    assert assign_severity("2.1.1", Level.A, "pass", AUTH, "critical") is Severity.MINOR


def test_level_aaa_is_capped_at_moderate():
    """
    AAA is explicitly not required for conformance. A AAA failure must never
    outrank a level A one.
    """
    assert assign_severity("1.4.6", Level.AAA, "fail", AUTH, "critical") is Severity.MODERATE


# --- engine impact as a hint ----------------------------------------------

@pytest.mark.parametrize(
    "impact,expected",
    [
        ("critical", Severity.CRITICAL),
        ("serious", Severity.SERIOUS),
        ("moderate", Severity.MODERATE),
        ("minor", Severity.MINOR),
    ],
)
def test_engine_impact_is_honoured_on_non_blocking_criteria(impact, expected):
    assert assign_severity("1.4.3", Level.AA, "fail", AUTH, impact) is expected


def test_unknown_engine_impact_falls_back_to_moderate_without_raising():
    """
    A new axe release inventing an impact string must not crash a scan or
    silently become `critical`.
    """
    assert assign_severity("1.4.3", Level.AA, "fail", AUTH, "catastrophic") is Severity.MODERATE
    assert assign_severity("1.4.3", Level.AA, "fail", AUTH, None) is Severity.MODERATE


def test_engine_impact_is_case_insensitive():
    assert assign_severity("1.4.3", Level.AA, "fail", AUTH, "SERIOUS") is Severity.SERIOUS


# --- explanation -----------------------------------------------------------

def test_explain_severity_gives_the_reason_not_just_the_verdict():
    """
    "Why is this only moderate?" is the first question anyone asks of a
    triage list. Answering it from the report beats answering from source.
    """
    result = explain_severity("2.1.1", Level.A, "cantTell", REVIEW)
    assert result["severity"] == "moderate"
    assert any("blocks operation" in r for r in result["basis"])
    assert any("undecided" in r for r in result["basis"])


def test_explain_agrees_with_assign():
    cases = [
        ("2.1.1", Level.A, "fail", AUTH, None),
        ("1.4.3", Level.AA, "cantTell", REVIEW, "serious"),
        ("1.4.6", Level.AAA, "fail", AUTH, "critical"),
        ("1.4.3", Level.AA, "pass", AUTH, "minor"),
    ]
    for args in cases:
        assert explain_severity(*args)["severity"] == assign_severity(*args).value


# --- B6.4: versioned, browser-free ----------------------------------------

def test_validator_is_versioned():
    """
    Waiver signatures and Week 7 baselines both depend on this module's
    behaviour staying pinned, so the version is load-bearing.
    """
    parts = VALIDATOR_VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_validator_imports_without_a_browser_or_a_model():
    """
    The stage that decides what reaches a user's build must be testable in
    milliseconds, with no Playwright installed and no page open — so there is
    never a reason to skip its tests.
    """
    import sys

    forbidden = {"playwright", "mlx", "mlx_vlm", "torch", "transformers"}
    already = {m for m in forbidden if m in sys.modules}

    import importlib
    for name in ["verity.agents.validator", "verity.agents.validator.dedup",
                 "verity.agents.validator.severity"]:
        importlib.reload(importlib.import_module(name))

    leaked = {m for m in forbidden if m in sys.modules} - already
    assert not leaked, f"validator pulled in browser/model dependencies: {leaked}"


def test_validator_public_surface_is_explicit():
    import verity.agents.validator as validator

    assert set(validator.__all__) <= set(dir(validator))
    for name in ["process_findings", "signature_for", "assign_severity", "VALIDATOR_VERSION"]:
        assert name in validator.__all__
