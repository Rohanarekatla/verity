"""
verity/agents/validator/dedup.py — deduplication and waiver application.

The waiver *schema* and expiry rules live in `waivers.py` (B7.1, B7.3); this
module applies them (B7.2). Keeping them apart matters because the schema is
pure data validation with no notion of a Finding, and it should stay
testable on its own.
"""

import hashlib
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from verity.models.schemas import Finding
from verity.agents.validator.selectors import normalize_selector

# The repo root, resolved from this file rather than the process cwd.
# `verity scan` has to behave the same from any directory — a waiver that
# silently stops applying because the user ran the CLI from somewhere else is
# an accepted failure quietly turning back into a build break, or worse, a
# real failure quietly staying waived.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WAIVERS_PATH = _REPO_ROOT / "waivers.yaml"


def generate_finding_signature(
    sc_id: str,
    selector: str,
    rule_id: str,
    *,
    region: str = "",
) -> str:
    """
    Deterministic identity for a finding: (success criterion, normalised
    selector or region, rule).

    A7.1: the selector is run through `normalize_selector` so the signature
    survives a code formatter and a class-name hasher — a raw axe selector
    carries `Button__a1b2c3`-style hashes that churn every build, and keying
    on them makes every waiver and baseline stop matching the morning after a
    team runs their bundler.

    A6.2: when the selector normalises to nothing stable (empty, or entirely
    hashed away), fall back to a caller-supplied `region` identity rather than
    collapsing every selector-less finding onto one key. An empty identity on
    both would make two unrelated findings share a signature — and a waiver
    for one silently suppress the other.

    `rule_id` is the engine's own rule name, taken from `Finding.rule_id`. It
    is not recovered from `Finding.id` by string-splitting: that made the
    signature depend on the exact format of an unrelated field.
    """
    norm_selector = normalize_selector(selector)
    identity = norm_selector or region or "no-selector"

    signature_payload = f"{sc_id}|{identity}|{rule_id}"
    return hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()


def region_identity(finding: Finding) -> str:
    """
    A6.2 — a stable fallback identity for a finding with no usable selector.

    Built from the evidence that does not churn: the accessible name and the
    rounded bounding box of the region, when present. This is deliberately
    coarse; its only job is to keep two genuinely different selector-less
    findings from colliding, not to be a precise locator.
    """
    ev = finding.evidence
    parts: list[str] = []
    name = (ev.computed_values or {}).get("accessible_name")
    if isinstance(name, str) and name.strip():
        parts.append(f"name={' '.join(name.split())}")
    box = ev.region
    if box is not None:
        # Round to whole pixels: sub-pixel jitter from a re-render must not
        # change identity.
        parts.append(
            "box=%d,%d,%d,%d"
            % (round(box.x), round(box.y), round(box.width), round(box.height))
        )
    return "|".join(parts)


def signature_for(finding: Finding) -> str:
    """The signature of an existing Finding. One definition, used everywhere."""
    return generate_finding_signature(
        finding.sc.id,
        finding.evidence.dom_selector or "",
        finding.rule_id,
        region=region_identity(finding),
    )


def load_waivers(waivers_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """
    Load and validate the waiver file (B7.1).

    Thin delegation to `waivers.load_waivers`, kept so the existing import
    surface does not change. Returns `{signature: Waiver}` — every record is
    schema-checked, so a malformed waiver raises rather than being skipped.
    """
    from verity.agents.validator.waivers import load_waivers as _load

    return _load(waivers_path)


def process_findings(
    findings: List[Finding],
    waivers_path: Optional[Path | str] = None,
    today: Optional[date] = None,
) -> List[Finding]:
    """
    Deduplicate findings and apply waivers to matching signatures.

    First occurrence wins on a collision. Callers map the `violations` bucket
    before the `incomplete` bucket, so where the same rule and selector appear
    in both, the authoritative result is the one kept and the undecided
    duplicate is dropped — which is the right way round.

    **Only *active* waivers suppress (B7.3).** An expired waiver is not
    applied, so the finding it used to cover reappears and gates normally —
    which is what an expiry date is for. The lapsed waiver is still recorded
    on the finding under `waiver_expired`, because "this was waived and the
    waiver ran out on 3 March" is exactly what a reader needs; a finding that
    silently reappears looks like a false positive.

    `today` is injectable so expiry behaviour is testable without freezing
    the clock.
    """
    from verity.agents.validator.waivers import active_waivers

    all_waivers = load_waivers(waivers_path)
    live = active_waivers(all_waivers, today)
    lapsed = {s: w for s, w in all_waivers.items() if s not in live}

    unique_findings: Dict[str, Finding] = {}

    for finding in findings:
        signature = signature_for(finding)

        if signature in unique_findings:
            continue

        waiver = live.get(signature)
        if waiver is not None:
            finding.waived = True
            # Attach waiver metadata to the finding's evidence computed values
            finding.evidence.computed_values["waiver"] = {
                "signature": signature,
                "justification": waiver.justification,
                "approved_by": waiver.approved_by,
                "created": waiver.created.isoformat(),
                "expires": waiver.expires.isoformat(),
            }
        elif signature in lapsed:
            expired = lapsed[signature]
            # Deliberately does NOT set waived=True — the finding gates again.
            finding.evidence.computed_values["waiver_expired"] = {
                "signature": signature,
                "justification": expired.justification,
                "approved_by": expired.approved_by,
                "expired_on": expired.expires.isoformat(),
            }

        unique_findings[signature] = finding

    return list(unique_findings.values())
