import hashlib
import yaml
from pathlib import Path
from typing import List, Dict, Any
from verity.models.schemas import Finding

def generate_finding_signature(sc_id: str, selector: str, rule_id: str) -> str:
    """
    Generates a deterministic hash based on SC id, normalised selector, and rule id.
    """
    # Normalize selector by collapsing whitespace
    norm_selector = " ".join(selector.split()) if selector else "no-selector"
    
    # Isolate the base rule ID (stripping the trailing hash added in main.py)
    base_rule_id = rule_id.rsplit('-', 1)[0] if '-' in rule_id else rule_id
    
    signature_payload = f"{sc_id}|{norm_selector}|{base_rule_id}"
    return hashlib.sha256(signature_payload.encode('utf-8')).hexdigest()

def load_waivers(waivers_path: str = "waivers.yaml") -> Dict[str, Any]:
    """
    Loads active waivers from the YAML configuration.
    """
    path = Path(waivers_path)
    if not path.exists():
        return {}
        
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
        # Assuming waivers are keyed by finding_signature or listed under partialFingerprints
        return data.get("partialFingerprints", {})

def process_findings(findings: List[Finding], waivers_path: str = "waivers.yaml") -> List[Finding]:
    """
    Deduplicates findings and applies waivers to matching signatures.
    """
    waivers = load_waivers(waivers_path)
    unique_findings: Dict[str, Finding] = {}

    for finding in findings:
        selector = finding.evidence.dom_selector or ""
        signature = generate_finding_signature(finding.sc.id, selector, finding.id)
        
        # Deduplication: If we haven't seen this signature, process it
        if signature not in unique_findings:
            
            # Waiver Matching
            if signature in waivers:
                waiver_record = waivers[signature]
                finding.waived = True
                
                # Attach waiver metadata to the finding's evidence computed values
                finding.evidence.computed_values["waiver"] = {
                    "justification": waiver_record.get("justification", "No justification provided"),
                    "approved_by": waiver_record.get("approved_by", "Unknown"),
                    "created": waiver_record.get("created"),
                    "expires": waiver_record.get("expires")
                }
                
            unique_findings[signature] = finding

    return list(unique_findings.values())