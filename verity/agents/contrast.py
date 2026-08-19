# File: verity/agents/contrast.py

from verity.models.schemas import Confidence, Finding, Modality, Provenance

def _normalize_srgb(c: int) -> float:
    """
    Applies the sRGB curve adjustment.
    """
    c_norm = c / 255.0
    return c_norm / 12.92 if c_norm <= 0.03928 else ((c_norm + 0.055) / 1.055) ** 2.4

def calculate_relative_luminance(r: int, g: int, b: int) -> float:
    """
    Calculates the relative luminance of a color.
    """
    R = _normalize_srgb(r)
    G = _normalize_srgb(g)
    B = _normalize_srgb(b)
    
    return 0.2126 * R + 0.7152 * G + 0.0722 * B

def calculate_contrast_ratio(l1: float, l2: float) -> float:
    """
    Calculates the contrast ratio between two relative luminances.
    """
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)

def flag_needs_review(finding: Finding) -> Finding:
    """
    Incomplete contrast findings must start with NEEDS_REVIEW provenance
    and an outcome of cantTell until adjudicated.

    The confidence and modality are reset alongside them. They arrive from
    the mapper describing an authoritative axe violation — score 1.0, method
    "deterministic", modality DETERMINISTIC — and axe's `incomplete` bucket
    means precisely that axe could *not* decide. Leaving that metadata in
    place ships a `cantTell` finding claiming full deterministic confidence,
    and provenance is the one thing in this product that has to be exactly
    true.
    """
    finding.provenance = Provenance.NEEDS_REVIEW
    finding.outcome = "cantTell"
    finding.confidence = Confidence(
        score=0.0,
        method="axe-incomplete",
        model=None,
        escape_used=False,
    )
    finding.sc.modality = Modality.PARTIAL
    return finding