"""
export_schema.py
Exports Pydantic models to JSON Schema to enforce the cross-language boundary.
"""
import json
from pathlib import Path
from pydantic.json_schema import models_json_schema

from verity.models.schemas import (
    AuditReport, RenderArtifact, Finding, PageState, 
    Evidence, Confidence, SuccessCriterion, BoundingBox
)

def export_to_json():
    # Generate a combined JSON schema for the core boundary models
    _, top_level_schema = models_json_schema([
        (AuditReport, "serialization"),
        (RenderArtifact, "serialization")
    ])
    
    out_path = Path("verity-schema.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(top_level_schema, f, indent=2)
        
    print(f"JSON Schema successfully exported to {out_path.resolve()}")

if __name__ == "__main__":
    export_to_json()