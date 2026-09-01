"""
A3.4 — sampleRegion is callable from Python and round-trips through the
shared schema. This drives the real worker (render -> sampleRegion) and
validates the payload against RegionSample, proving the two sides agree.

Skipped when the worker isn't built, so the Python-only CI job doesn't fail
on a missing dist/ — the Node CI job builds and exercises the TS side.
"""

import asyncio
from pathlib import Path

import pytest

from verity.models.schemas import RegionSample

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"
FIXTURE = REPO / "data" / "fixtures" / "contrast-sampling.html"

pytestmark = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


async def _sample(selector: str) -> RegionSample:
    from verity.orchestrator.rpc_client import RPCClient

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=60.0)
    await client.start()
    try:
        render = await client.send_request("render", {"url": FIXTURE.as_uri()})
        raw = await client.send_request(
            "sampleRegion",
            {"artifactId": render["artifactId"], "selector": selector},
        )
        await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
        # The round-trip: the worker's JSON must validate as RegionSample.
        return RegionSample.model_validate(raw)
    finally:
        await client.stop()


@pytest.mark.asyncio
async def test_solid_background_round_trips_and_is_exact():
    sample = await _sample("#solid-grey")
    assert sample.sampled
    assert (sample.foreground.r, sample.foreground.g, sample.foreground.b) == (255, 255, 255)
    top = sample.background_samples[0]
    # A3.2: the estimated background equals the CSS background (#808080) exactly.
    assert (top.r, top.g, top.b) == (128, 128, 128)
    assert top.count > 0
    assert sample.ambiguous is False


@pytest.mark.asyncio
async def test_text_over_image_is_flagged_ambiguous():
    sample = await _sample("#over-image")
    assert sample.sampled
    # An adjudicator must not pass this on the deterministic path alone.
    assert sample.ambiguous is True
