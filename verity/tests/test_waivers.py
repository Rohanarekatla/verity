"""
Tests for B7.1 (waiver schema), B7.2 (suppression) and B7.3 (expiry).

Week 7 exists because without waivers the first team to install Verity sees
several hundred pre-existing failures and uninstalls it. But a waiver is a
decision to stop looking at a real defect, so the schema is unforgiving and
the expiry is real. Most of these tests are about what the schema *rejects*.
"""

import textwrap
from datetime import date, timedelta

import pytest

from verity.agents.validator import (
    VALIDATOR_VERSION,
    Waiver,
    WaiverFileError,
    active_waivers,
    expired_waivers,
    expiring_soon,
    load_waivers,
    parse_waivers,
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

SIG = "a" * 64
TODAY = date(2026, 10, 12)


def make_finding(selector: str = "#btn") -> Finding:
    return Finding(
        id="color-contrast-abc123abc123",
        rule_id="color-contrast",
        sc=SuccessCriterion(
            id="1.4.3", name="Contrast (Minimum)", level=Level.AA,
            modality=Modality.DETERMINISTIC,
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


def waiver_file(tmp_path, signature: str, **overrides) -> "object":
    fields = {
        "justification": "Brand colours signed off by the design team.",
        "approved_by": "Design Lead",
        "created": "2026-08-17",
        "expires": "2027-08-17",
    }
    fields.update(overrides)
    body = "\n".join(f'    {k}: "{v}"' for k, v in fields.items())
    path = tmp_path / "waivers.yaml"
    path.write_text(
        f'partialFingerprints:\n  "{signature}":\n{body}\n', encoding="utf-8"
    )
    return path


# --- B7.1: every field required -------------------------------------------

@pytest.mark.parametrize(
    "omit", ["justification", "approved_by", "created", "expires"]
)
def test_every_field_is_required_and_the_error_names_the_waiver(tmp_path, omit):
    """
    An incomplete waiver is an error, not an ignored line. Silently skipping
    it means the team believes a finding is suppressed when it is not.
    """
    fields = {
        "justification": "Brand colours signed off by the design team.",
        "approved_by": "Design Lead",
        "created": "2026-08-17",
        "expires": "2027-08-17",
    }
    del fields[omit]
    path = waiver_file(tmp_path, SIG, **{})
    body = "\n".join(f'    {k}: "{v}"' for k, v in fields.items())
    path.write_text(
        f'partialFingerprints:\n  "{SIG}":\n{body}\n', encoding="utf-8"
    )

    with pytest.raises(WaiverFileError) as exc:
        load_waivers(path)

    assert omit in str(exc.value)
    assert SIG[:12] in str(exc.value), "the error must name which waiver"


def test_a_complete_waiver_loads():
    waiver = Waiver.model_validate({
        "signature": SIG,
        "justification": "Brand colours signed off by the design team.",
        "approved_by": "Design Lead",
        "created": "2026-08-17",
        "expires": "2027-08-17",
    })
    assert waiver.approved_by == "Design Lead"
    assert waiver.expires == date(2027, 8, 17)


@pytest.mark.parametrize("placeholder", ["n/a", "TBD", "ok", "wontfix", "known issue"])
def test_placeholder_justifications_are_rejected(placeholder):
    """
    "n/a", "-" and "ok" are what people type when a field is required but
    not enforced. None of them is a justification.
    """
    with pytest.raises(Exception):
        Waiver.model_validate({
            "signature": SIG, "justification": placeholder,
            "approved_by": "X", "created": "2026-01-01", "expires": "2027-01-01",
        })


def test_short_justification_is_rejected():
    with pytest.raises(Exception):
        Waiver.model_validate({
            "signature": SIG, "justification": "too short",
            "approved_by": "X", "created": "2026-01-01", "expires": "2027-01-01",
        })


def test_expiry_must_be_after_creation():
    """A waiver expiring on the day it was written never suppressed anything."""
    with pytest.raises(Exception, match="must be after created"):
        Waiver.model_validate({
            "signature": SIG,
            "justification": "Backwards dates, should not validate.",
            "approved_by": "X", "created": "2027-01-01", "expires": "2026-01-01",
        })


@pytest.mark.parametrize("bad", ["z" * 64, "abc", "a" * 63, "a" * 65])
def test_signature_must_be_a_64_char_hex_digest(bad):
    with pytest.raises(Exception):
        Waiver.model_validate({
            "signature": bad,
            "justification": "A plausible reason that is long enough.",
            "approved_by": "X", "created": "2026-01-01", "expires": "2027-01-01",
        })


def test_approver_is_accepted_as_a_spelling_of_approved_by():
    """
    The execution plan names the field "approver"; the code and template use
    `approved_by`. A file written from either must parse, or the first thing
    a reader of the plan writes gets rejected.
    """
    parsed = parse_waivers({
        "partialFingerprints": {
            SIG: {
                "justification": "Written from the plan's field names.",
                "approver": "Design Lead",
                "created": "2026-08-17",
                "expires": "2027-08-17",
            }
        }
    })
    assert parsed[SIG].approved_by == "Design Lead"


def test_unknown_fields_are_rejected(tmp_path):
    """A typo'd field name must not be silently dropped."""
    with pytest.raises(Exception):
        Waiver.model_validate({
            "signature": SIG,
            "justification": "A plausible reason that is long enough.",
            "approved_by": "X", "created": "2026-01-01", "expires": "2027-01-01",
            "expiry": "2028-01-01",  # typo for `expires`
        })


def test_broken_yaml_is_reported_as_such(tmp_path):
    path = tmp_path / "waivers.yaml"
    path.write_text("partialFingerprints:\n  : : :\n", encoding="utf-8")
    with pytest.raises(WaiverFileError, match="not valid YAML"):
        load_waivers(path)


def test_missing_file_means_no_waivers(tmp_path):
    assert load_waivers(tmp_path / "nope.yaml") == {}


def test_committed_waivers_file_still_validates():
    """The shipped template must parse — and waive nothing."""
    assert load_waivers() == {}


# --- B7.2: suppression ----------------------------------------------------

def test_waived_finding_is_marked_excluded_from_gating_and_kept_in_report(tmp_path):
    """
    All four properties at once, because they are easy to get partly right:
    marked waived, out of the gate, out of conformance, still in the report.
    """
    from verity.orchestrator.main import build_conformance_map
    from verity.report.policy import DEFAULT_POLICY

    finding = make_finding()
    path = waiver_file(tmp_path, signature_for(finding))

    out = process_findings([finding], waivers_path=path, today=TODAY)

    assert len(out) == 1, "the finding is RETAINED in the report, not deleted"
    assert out[0].waived is True

    # Asked of the real policy (B8.4) rather than a re-implemented filter, so
    # this test fails if the gating rule and the waiver rule ever disagree.
    assert DEFAULT_POLICY.gating_findings(out) == [], (
        "a waived finding must not gate the build"
    )
    assert DEFAULT_POLICY.annotated_findings(out) == out, (
        "a waived finding must still appear in the report"
    )

    assert build_conformance_map(out) == {}, "waived findings leave conformance clear"

    waiver = out[0].evidence.computed_values["waiver"]
    assert waiver["approved_by"] == "Design Lead"
    assert waiver["expires"] == "2027-08-17"


def test_waiver_metadata_survives_json_round_trip(tmp_path):
    """The report is the artefact a reviewer reads; the reason must survive."""
    finding = make_finding()
    path = waiver_file(tmp_path, signature_for(finding))
    out = process_findings([finding], waivers_path=path, today=TODAY)

    restored = Finding.model_validate_json(out[0].model_dump_json())
    assert restored.waived is True
    assert restored.evidence.computed_values["waiver"]["justification"]


# --- B7.3: expiry ---------------------------------------------------------

def test_expired_waiver_stops_suppressing(tmp_path):
    """
    The point of an expiry date. The finding reappears and gates again.
    """
    finding = make_finding()
    path = waiver_file(
        tmp_path, signature_for(finding),
        created="2025-01-01", expires="2026-01-01",
    )

    out = process_findings([finding], waivers_path=path, today=TODAY)
    assert out[0].waived is False, "an expired waiver must not suppress"


def test_expired_waiver_explains_itself_on_the_finding(tmp_path):
    """
    A finding that silently reappears looks like a false positive. The lapsed
    waiver is recorded so a reader knows why it is back.
    """
    finding = make_finding()
    path = waiver_file(
        tmp_path, signature_for(finding),
        created="2025-01-01", expires="2026-01-01",
    )

    out = process_findings([finding], waivers_path=path, today=TODAY)
    lapsed = out[0].evidence.computed_values["waiver_expired"]
    assert lapsed["expired_on"] == "2026-01-01"
    assert lapsed["approved_by"] == "Design Lead"
    assert "waiver" not in out[0].evidence.computed_values


def test_expired_waivers_are_listed_by_name(tmp_path):
    """B7.3 — CI must fail *naming* the waiver, not just counting them."""
    path = waiver_file(tmp_path, SIG, created="2025-01-01", expires="2026-01-01")
    expired = expired_waivers(load_waivers(path), today=TODAY)

    assert len(expired) == 1
    described = expired[0].describe()
    assert SIG[:12] in described
    assert "2026-01-01" in described
    assert "Design Lead" in described
    assert expired[0].days_overdue == (TODAY - date(2026, 1, 1)).days


def test_the_expiry_day_itself_is_still_valid():
    """
    `expires: 2026-12-31` means "good through the 31st" — how anyone reads a
    date on a permission slip.
    """
    waiver = Waiver.model_validate({
        "signature": SIG, "justification": "Valid through the stated day.",
        "approved_by": "X", "created": "2026-01-01", "expires": "2026-10-12",
    })
    assert waiver.is_expired(date(2026, 10, 12)) is False
    assert waiver.is_expired(date(2026, 10, 13)) is True


def test_active_and_expired_partition_the_set(tmp_path):
    waivers = parse_waivers({
        "partialFingerprints": {
            "a" * 64: {
                "justification": "Still current, expires next year.",
                "approved_by": "X", "created": "2026-01-01", "expires": "2027-01-01",
            },
            "b" * 64: {
                "justification": "Lapsed at the start of this year.",
                "approved_by": "X", "created": "2025-01-01", "expires": "2026-01-01",
            },
        }
    })
    live = active_waivers(waivers, TODAY)
    dead = expired_waivers(waivers, TODAY)

    assert set(live) == {"a" * 64}
    assert [e.signature for e in dead] == ["b" * 64]
    assert len(live) + len(dead) == len(waivers)


def test_expiring_soon_warns_before_it_bites(tmp_path):
    """
    A hard expiry with no warning turns a deliberate policy into a surprise
    red build on an unrelated PR.
    """
    soon = (TODAY + timedelta(days=10)).isoformat()
    later = (TODAY + timedelta(days=200)).isoformat()
    waivers = parse_waivers({
        "partialFingerprints": {
            "a" * 64: {
                "justification": "Lapses in ten days, should warn.",
                "approved_by": "X", "created": "2026-01-01", "expires": soon,
            },
            "b" * 64: {
                "justification": "Lapses much later, should stay quiet.",
                "approved_by": "X", "created": "2026-01-01", "expires": later,
            },
        }
    })
    warned = expiring_soon(waivers, within_days=30, today=TODAY)
    assert [s for s, _, _ in warned] == ["a" * 64]
    assert warned[0][2] == 10


def test_cli_reports_expired_waivers_and_returns_them(tmp_path, capsys):
    from verity.cli import report_expired_waivers

    path = waiver_file(tmp_path, SIG, created="2025-01-01", expires="2026-01-01")
    returned = report_expired_waivers(str(path))

    assert len(returned) == 1
    printed = capsys.readouterr().out
    assert "EXPIRED WAIVERS" in printed
    assert SIG[:12] in printed


def test_cli_surfaces_a_broken_waiver_file_rather_than_ignoring_it(tmp_path, capsys):
    """
    If we cannot tell which findings are suppressed, continuing as though
    none were would be a guess about someone's accessibility policy.
    """
    from verity.cli import report_expired_waivers

    path = tmp_path / "waivers.yaml"
    path.write_text(
        f'partialFingerprints:\n  "{SIG}":\n    justification: "x"\n',
        encoding="utf-8",
    )
    returned = report_expired_waivers(str(path))

    assert returned, "a broken waiver file must fail, not pass silently"
    assert "WAIVER FILE INVALID" in capsys.readouterr().out


def test_validator_version_bumped_major_for_the_behaviour_change():
    """
    B7.1/B7.3 change observable behaviour: files that loaded before may now
    be rejected, and a waiver past its date stops working. Waiver signatures
    and Week 7 baselines are pinned to this number.
    """
    assert VALIDATOR_VERSION.split(".")[0] == "2"
