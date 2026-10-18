"""
verity/agents/validator — the validation stage (B6.4).

Everything here runs on a `list[Finding]` and nothing else. **No browser, no
network, no model.** That is the point: the stage that decides what reaches a
user's build must be testable in milliseconds, without Playwright installed
and without a page open, so there is never a reason to skip its tests.

The import surface is deliberately small and the module is versioned, because
two things downstream depend on its behaviour staying pinned:

- **waiver signatures** — change how a signature is computed and every waiver
  a team has written silently stops matching
- **baseline diffs** (Week 7) — a baseline is only comparable to a scan run
  by the same validator

So `VALIDATOR_VERSION` is not decoration. Bump it whenever the *observable*
behaviour changes — the signature scheme, the dedup rule, the severity
policy — and leave it alone for refactors that cannot change an output.
"""

from .dedup import (
    DEFAULT_WAIVERS_PATH,
    generate_finding_signature,
    load_waivers,
    process_findings,
    region_identity,
    signature_for,
)
from .selectors import normalize_selector
from .severity import assign_severity, explain_severity
from .waivers import (
    ExpiredWaiver,
    Waiver,
    WaiverFileError,
    active_waivers,
    expired_waivers,
    expiring_soon,
    parse_waivers,
)

# Semantic, and about behaviour rather than code.
#
#   1.0.0  Week 2  first-wins dedup; signature = sha256(sc|selector|rule)
#   1.1.0  Week 6  severity policy (B6.3); provenance coherence enforced at
#                  construction (B6.2, in models/schemas.py)
#   2.0.0  Week 7  waiver schema with every field required (B7.1); expired
#                  waivers no longer suppress (B7.3). MAJOR because a waiver
#                  file that loaded before may now be rejected, and a waiver
#                  past its date stops working — both are behaviour changes a
#                  consumer can observe.
#   3.0.0  Week 6/7 signature keys on the NORMALISED selector (A6.1) with a
#                  region fallback (A6.2); A7.1 — the signature now survives a
#                  code formatter and a class-name hasher. MAJOR because the
#                  signature of an unchanged finding changes, so every waiver
#                  written against the 2.x scheme stops matching and must be
#                  re-captured. Safe to land now: the shipped waivers.yaml
#                  waives nothing, so no real waiver is invalidated in the wild
#                  yet — which is exactly why this goes in before teams write
#                  real waivers, not after.
VALIDATOR_VERSION = "3.0.0"

__all__ = [
    "VALIDATOR_VERSION",
    "DEFAULT_WAIVERS_PATH",
    "ExpiredWaiver",
    "Waiver",
    "WaiverFileError",
    "active_waivers",
    "assign_severity",
    "expired_waivers",
    "expiring_soon",
    "normalize_selector",
    "region_identity",
    "explain_severity",
    "generate_finding_signature",
    "load_waivers",
    "parse_waivers",
    "process_findings",
    "signature_for",
]
