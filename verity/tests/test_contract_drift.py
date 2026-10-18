"""
A6.3 — the committed cross-language contract must match the Python models.

Two kinds of silent drift this pins:

1. Someone edits a boundary model in schemas.py but forgets to re-run
   export_schema.py, so `verity-schema.json` is stale and Track A builds to an
   old shape. (This actually happened — the committed schema was stale against
   a B6.2 docstring change before A6.3 landed.)
2. The schema changes but the generated TypeScript mirror
   (`node-worker/contract/contract-types.ts`) is not regenerated, so the
   worker's typed contract lags the Python one — the `element_screenshots`
   Week-2 drift, mechanised away.

The fix when this test goes red is mechanical, and the failure message says so:
`uv run python export_schema.py && uv run python generate_ts_contract.py`,
then commit the result.
"""

from pathlib import Path

import export_schema
import generate_ts_contract

REPO = Path(__file__).resolve().parents[2]
SCHEMA = REPO / "verity-schema.json"
TS_MIRROR = REPO / "node-worker" / "contract" / "contract-types.ts"

_REGEN = (
    "Run `uv run python export_schema.py && uv run python generate_ts_contract.py` "
    "and commit the result."
)


def test_committed_schema_matches_the_models():
    committed = SCHEMA.read_text(encoding="utf-8")
    current = export_schema.schema_json()
    assert committed == current, (
        "verity-schema.json is stale against verity/models/schemas.py. " + _REGEN
    )


def test_committed_ts_mirror_matches_the_schema():
    committed = TS_MIRROR.read_text(encoding="utf-8")
    current = generate_ts_contract.render_ts(export_schema.build_schema())
    assert committed == current, (
        "node-worker/contract/contract-types.ts is stale against the schema. " + _REGEN
    )


def test_boundary_payloads_are_in_the_contract():
    """
    The worker-return payloads are not reachable from the AuditReport root, so
    they have to be listed in export_schema explicitly or they silently vanish
    from the contract. Pin that they are present.
    """
    defs = export_schema.build_schema().get("$defs", {})
    for name in ("RegionSample", "TraversalResult", "TabStop", "UnreachedRegion"):
        assert name in defs, f"{name} dropped out of the exported contract"
