"""
verity/report — output formats and gating policy (Week 8).

Three things live here, and they are separate on purpose:

- `policy.py` (B8.4) — what fails the build vs what merely appears. Both
  generators read it, so there is one answer to "does this gate" rather than
  three that can drift.
- `sarif.py` (B8.1, B8.2) — SARIF 2.1.0 for GitHub code scanning.
- `junit.py` (B8.3) — JUnit XML for every CI that is not GitHub Actions.

Like the validator package, nothing here imports a browser or a model. A
report format should be testable from a hand-built `AuditReport` in
milliseconds.
"""

from verity.report.junit import build_junit, write_junit
from verity.report.policy import DEFAULT_POLICY, GATE_LEVELS, CiPolicy, load_policy
from verity.report.sarif import (
    FINGERPRINT_KEY,
    SARIF_VERSION,
    build_sarif,
    repo_relative_path,
    sarif_level,
    write_sarif,
)

__all__ = [
    "CiPolicy",
    "DEFAULT_POLICY",
    "FINGERPRINT_KEY",
    "GATE_LEVELS",
    "SARIF_VERSION",
    "build_junit",
    "build_sarif",
    "load_policy",
    "repo_relative_path",
    "sarif_level",
    "write_junit",
    "write_sarif",
]
