"""
A7.2 — baseline storage and diff.

The properties that matter for Week 8's gate ("one new defect fails the build,
not fifty old ones"):

- the content address is stable across re-records and order, so an unchanged
  baseline doesn't look changed in a PR;
- a new finding shows up as `new` (and gates); a disappeared one as `fixed`;
- a hand-edited baseline file is rejected, not trusted;
- a validator-major mismatch is flagged rather than silently producing a
  nonsense all-new/all-fixed diff.
"""

from datetime import datetime, timezone

import pytest

from verity.models.schemas import (
    AuditReport, Finding, SuccessCriterion, Evidence, Confidence,
    Level, Modality, Provenance, Severity, Latency,
)
from verity.report.baseline import (
    build_baseline, store_baseline, load_baseline, diff_report, format_diff,
)


def _finding(sc_id="1.4.3", rule_id="color-contrast", selector="#hero",
             severity=Severity.SERIOUS, waived=False) -> Finding:
    f = Finding(
        id=f"{rule_id}-abc123abc123",
        rule_id=rule_id,
        sc=SuccessCriterion(id=sc_id, name="x", level=Level.AA, modality=Modality.DETERMINISTIC),
        provenance=Provenance.AUTHORITATIVE,
        severity=severity,
        confidence=Confidence(score=1.0, method="deterministic"),
        agent="axe-core",
        outcome="fail",
        message="m",
        evidence=Evidence(dom_selector=selector),
        page_state_hash="h",
    )
    if waived:
        f.waived = True
    return f


def _report(*findings, target="https://example.com") -> AuditReport:
    return AuditReport(
        target=target, standard="WCAG2.2-AA", findings=list(findings),
        conformance={}, verity_version="0.1.0", ruleset_version="1.0.0",
        latency=Latency(render_seconds=1.0, analysis_seconds=0.5, total_seconds=2.0),
    )


def test_baseline_id_is_stable_across_record_time_and_order():
    r1 = _report(_finding(selector="#a"), _finding(selector="#b"))
    r2 = _report(_finding(selector="#b"), _finding(selector="#a"))  # reversed
    b1 = build_baseline(r1, created=datetime(2026, 1, 1, tzinfo=timezone.utc))
    b2 = build_baseline(r2, created=datetime(2026, 9, 9, tzinfo=timezone.utc))  # later
    assert b1.baseline_id == b2.baseline_id, "id must ignore order and timestamp"


def test_waived_findings_are_not_baselined():
    r = _report(_finding(selector="#a"), _finding(selector="#b", waived=True))
    b = build_baseline(r)
    assert len(b.entries) == 1


def test_diff_detects_a_new_finding_as_a_regression():
    base = build_baseline(_report(_finding(selector="#a")))
    scan = _report(_finding(selector="#a"), _finding(selector="#b"))  # #b is new
    d = diff_report(base, scan)
    assert d.is_regression
    assert len(d.new) == 1 and d.new[0].evidence.dom_selector == "#b"
    assert len(d.unchanged) == 1
    assert d.fixed == []


def test_diff_detects_a_fixed_finding():
    base = build_baseline(_report(_finding(selector="#a"), _finding(selector="#b")))
    scan = _report(_finding(selector="#a"))  # #b fixed
    d = diff_report(base, scan)
    assert not d.is_regression
    assert len(d.fixed) == 1
    assert len(d.unchanged) == 1


def test_identical_scan_is_clean():
    r = _report(_finding(selector="#a"), _finding(selector="#b"))
    d = diff_report(build_baseline(r), r)
    assert not d.is_regression
    assert d.new == [] and d.fixed == []
    assert len(d.unchanged) == 2


def test_roundtrip_through_disk(tmp_path):
    b = build_baseline(_report(_finding(selector="#a")))
    path = store_baseline(b, root=tmp_path)
    assert path.name == f"{b.baseline_id}.json"
    loaded = load_baseline(path)
    assert loaded.baseline_id == b.baseline_id
    assert loaded.signatures == b.signatures


def test_hand_edited_baseline_is_rejected(tmp_path):
    b = build_baseline(_report(_finding(selector="#a")))
    path = store_baseline(b, root=tmp_path)
    # Tamper: add a signature to the file without fixing the content address.
    text = path.read_text()
    text = text.replace('"entries": [', '"entries": [\n    {"signature": "%s", "sc_id": "1.1.1", "rule_id": "image-alt", "severity": "critical", "provenance": "authoritative"},' % ("f" * 64))
    path.write_text(text)
    with pytest.raises(ValueError, match="does not match contents"):
        load_baseline(path)


def test_validator_major_mismatch_is_flagged():
    b = build_baseline(_report(_finding(selector="#a")))
    # Simulate a baseline recorded under an older validator major (1.x) —
    # different from both main (2.x) and post-A7.1 (3.x), so this stays a
    # genuine mismatch whatever the current scheme.
    b.validator_version = "1.0.0"
    d = diff_report(b, _report(_finding(selector="#a")))
    assert d.version_mismatch is not None
    assert "re-recorded" in d.version_mismatch


def test_format_diff_is_readable():
    base = build_baseline(_report(_finding(selector="#a")))
    scan = _report(_finding(selector="#a"), _finding(selector="#b", sc_id="1.1.1", rule_id="image-alt"))
    text = format_diff(diff_report(base, scan))
    assert "1 new" in text
    assert "these gate the build" in text
    assert "image-alt" in text
