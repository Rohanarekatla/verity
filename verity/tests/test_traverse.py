"""
A4.1 — traverseTabOrder is callable from Python and round-trips through the
shared schema. Drives the real worker (render -> traverseTabOrder) and
validates the payload against TraversalResult, proving the two sides agree on
the contract keyboard.py reads.

Skipped when the worker isn't built, so the Python-only CI job doesn't fail on
a missing dist/ — the Node CI job builds and exercises the TS side.
"""

import pytest

from pathlib import Path

from verity.models.schemas import TraversalResult, UnreachedReason

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"
FIXTURES = REPO / "data" / "fixtures"

pytestmark = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


async def _traverse(fixture: str, **params) -> TraversalResult:
    from verity.orchestrator.rpc_client import RPCClient

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=60.0)
    await client.start()
    try:
        render = await client.send_request(
            "render", {"url": (FIXTURES / fixture).as_uri()}
        )
        raw = await client.send_request(
            "traverseTabOrder", {"artifactId": render["artifactId"], **params}
        )
        await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
        # The round-trip: the worker's JSON must validate as TraversalResult.
        return TraversalResult.model_validate(raw)
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_clean_tablist_round_trips_with_zero_barriers():
    """The gate, seen from Python: a clean APG widget yields no barrier."""
    result = await _traverse("keyboard-tablist.html", cyclesRequested=2)

    assert result.trap_detected is False
    assert result.complete is True
    assert result.cycles_completed == 2
    assert result.returned_to_origin is True

    barriers = [
        u for u in result.unreached
        if u.reason in (UnreachedReason.NOT_FOCUSABLE, UnreachedReason.OBSCURED)
    ]
    assert barriers == [], f"a clean widget has no barrier, got {barriers}"

    arrow = [u for u in result.unreached if u.reason is UnreachedReason.ARROW_NAVIGABLE]
    assert len(arrow) == 5, "the five roving tabs are arrow-navigable, not unreachable"


@pytest.mark.asyncio
async def test_trap_round_trips_as_a_detected_trap():
    result = await _traverse("keyboard-trap.html")
    assert result.trap_detected is True
    assert result.trap_selector == "#trap"


@pytest.mark.asyncio
async def test_authored_tabindex_survives_the_round_trip():
    result = await _traverse("keyboard-positive-tabindex.html")
    jumped = next(s for s in result.stops if s.selector == "#jumped")
    assert jumped.tabindex == 5
    natural = next(s for s in result.stops if s.selector == "#natural-a")
    assert natural.tabindex is None, "absent tabindex is None, never the computed 0"
