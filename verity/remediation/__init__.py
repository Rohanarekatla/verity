"""
Week 15 Track A — remediation support: mapping a finding back to the source the
fix loop must edit (A15.2′).
"""

from verity.remediation.source_map import (
    SourceLocation,
    locate_selector,
    resolve_source_map_position,
)

__all__ = ["SourceLocation", "locate_selector", "resolve_source_map_position"]
