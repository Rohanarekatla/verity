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
    WidgetInventory,
    ExerciseResult,
    InteractionStep,
    ImageInventory,
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
    # inventoryWidgets() -> WidgetInventory (A9.2)
    WidgetInventory,
    # exerciseWidget(steps: InteractionStep[]) -> ExerciseResult (A9.1, A9.3)
    InteractionStep,
    ExerciseResult,
    # inventoryImages() -> ImageInventory (A10.1)
    ImageInventory,
]


SCHEMA_PATH = Path(__file__).resolve().parent / "verity-schema.json"


def build_schema() -> dict:
    """The exported contract as a dict. One source of truth for the file
    writer and the drift test, so 'what we would write' and 'what we compare
    against' cannot diverge."""
    _, top_level_schema = models_json_schema(
        [(model, "serialization") for model in BOUNDARY_MODELS]
    )
    return top_level_schema


def schema_json() -> str:
    """The exact string form written to verity-schema.json (trailing newline
    included, so a file comparison is byte-for-byte)."""
    return json.dumps(build_schema(), indent=2) + "\n"


def export_to_json():
    SCHEMA_PATH.write_text(schema_json(), encoding="utf-8")

    exported = sorted(build_schema().get("$defs", {}))
    print(f"JSON Schema successfully exported to {SCHEMA_PATH}")
    print(f"{len(exported)} definitions: {', '.join(exported)}")


if __name__ == "__main__":
    export_to_json()
