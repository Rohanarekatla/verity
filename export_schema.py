"""
export_schema.py
Exports Pydantic models to JSON Schema to enforce the cross-language boundary.

Every model that crosses the Python/Node RPC boundary must appear in
`verity-schema.json`, or Track A has nothing to build against and the two
sides drift silently — which is exactly what happened to `element_screenshots`
in Week 2 and was only caught by reading the TypeScript by hand.

`models_json_schema` walks nested models automatically, so only the *roots*
need listing. But a root has to actually be reachable: `RegionSample` and
`TraversalResult` are RPC payloads that nothing in `AuditReport` or
`RenderArtifact` refers to, so they are listed explicitly. Anything added to
that class of "worker returns it, Python consumes it" models belongs here too.
"""
import json
from pathlib import Path
from pydantic.json_schema import models_json_schema

from verity.models.schemas import (
    AuditReport,
    RenderArtifact,
    # Worker payloads. Not reachable from the two roots above, so they must be
    # named here or they will not appear in the exported contract at all.
    RegionSample,
    TraversalResult,
)

# The roots of the cross-language contract. Nested models come along for free.
BOUNDARY_MODELS = [
    # The report the CLI writes.
    AuditReport,
    # render() -> RenderArtifact (A1.3, A2.2)
    RenderArtifact,
    # sampleRegion() -> RegionSample (A3.4)
    RegionSample,
    # tab-order traversal -> TraversalResult (A4.1, A4.2) — proposed, see
    # docs/Developer-A/week-4-action-items.md
    TraversalResult,
]


def export_to_json():
    _, top_level_schema = models_json_schema(
        [(model, "serialization") for model in BOUNDARY_MODELS]
    )

    out_path = Path(__file__).resolve().parent / "verity-schema.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(top_level_schema, f, indent=2)

    exported = sorted(top_level_schema.get("$defs", {}))
    print(f"JSON Schema successfully exported to {out_path}")
    print(f"{len(exported)} definitions: {', '.join(exported)}")


if __name__ == "__main__":
    export_to_json()
