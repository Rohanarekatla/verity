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
    signature_for,
)
from .severity import assign_severity, explain_severity

# Semantic, and about behaviour rather than code.
#
#   1.0.0  Week 2  first-wins dedup; signature = sha256(sc|selector|rule)
#   1.1.0  Week 6  severity policy (B6.3); provenance coherence enforced at
#                  construction (B6.2, in models/schemas.py)
#
# NOT yet changed: the dedup signature still keys on (sc, selector, rule_id).
# B6.1 calls for (SC, normalised selector, region) with strongest-provenance
# tie-breaking, which needs A6.1 (selector normalisation) and A6.2 (region
# identification) to exist first. That change will be a MAJOR bump, because
# it invalidates every waiver written against the old scheme.
VALIDATOR_VERSION = "1.1.0"

__all__ = [
    "VALIDATOR_VERSION",
    "DEFAULT_WAIVERS_PATH",
    "assign_severity",
    "explain_severity",
    "generate_finding_signature",
    "load_waivers",
    "process_findings",
    "signature_for",
]
