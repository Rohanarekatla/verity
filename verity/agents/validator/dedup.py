"""
verity/agents/validator/dedup.py — deduplication and waiver application.

Landed ahead of schedule (B6.1 dedup, B7.1/B7.2 waivers). Expiry enforcement
is B7.3 and is deliberately not implemented here.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from verity.models.schemas import Finding

# The repo root, resolved from this file rather than the process cwd.
# `verity scan` has to behave the same from any directory — a waiver that
# silently stops applying because the user ran the CLI from somewhere else is
# an accepted failure quietly turning back into a build break, or worse, a
# real failure quietly staying waived.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WAIVERS_PATH = _REPO_ROOT / "waivers.yaml"


def generate_finding_signature(sc_id: str, selector: str, rule_id: str) -> str:
    """
    Deterministic identity for a finding: (success criterion, selector, rule).

    `rule_id` is the engine's own rule name, taken from `Finding.rule_id`.
    It is not recovered from `Finding.id` by string-splitting: that made the
    signature depend on the exact format of an unrelated field, so changing
    how ids are built would silently invalidate every waiver in the file.
    """
    # Normalize selector by collapsing whitespace
    norm_selector = " ".join(selector.split()) if selector else "no-selector"

    signature_payload = f"{sc_id}|{norm_selector}|{rule_id}"
    return hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()


def signature_for(finding: Finding) -> str:
    """The signature of an existing Finding. One definition, used everywhere."""
    return generate_finding_signature(
        finding.sc.id,
        finding.evidence.dom_selector or "",
        finding.rule_id,
    )


def load_waivers(waivers_path: Optional[Path | str] = None) -> Dict[str, Any]:
    """
    Load active waivers from the YAML configuration.

    Defaults to the repo-root `waivers.yaml`, not a cwd-relative one.
    """
    path = Path(waivers_path) if waivers_path is not None else DEFAULT_WAIVERS_PATH
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    fingerprints = data.get("partialFingerprints") or {}
    if not isinstance(fingerprints, dict):
        raise ValueError(
            f"{path}: 'partialFingerprints' must be a mapping of "
            "signature -> waiver record"
        )
    return fingerprints


def process_findings(
    findings: List[Finding], waivers_path: Optional[Path | str] = None
) -> List[Finding]:
    """
    Deduplicate findings and apply waivers to matching signatures.

    First occurrence wins on a collision. Callers map the `violations` bucket
    before the `incomplete` bucket, so where the same rule and selector appear
    in both, the authoritative result is the one kept and the undecided
    duplicate is dropped — which is the right way round.
    """
    waivers = load_waivers(waivers_path)
    unique_findings: Dict[str, Finding] = {}

    for finding in findings:
        signature = signature_for(finding)

        if signature in unique_findings:
            continue

        waiver_record = waivers.get(signature)
        if isinstance(waiver_record, dict):
            finding.waived = True
            # Attach waiver metadata to the finding's evidence computed values
            finding.evidence.computed_values["waiver"] = {
                "signature": signature,
                "justification": waiver_record.get(
                    "justification", "No justification provided"
                ),
                "approved_by": waiver_record.get("approved_by", "Unknown"),
                "created": waiver_record.get("created"),
                "expires": waiver_record.get("expires"),
            }

        unique_findings[signature] = finding

    return list(unique_findings.values())
