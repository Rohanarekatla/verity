"""
A9.4 — the contract-fixture CI gate, against the real worker.

Every contract in data/apg-contracts/ ships a passing and a failing fixture.
On the pass fixture the runner must report zero failures and decide every
implemented violation; on the fail fixture at least one violation must fail.
A contract that cannot fail its own fail-fixture checks nothing, and this
gate is what refuses to ship it.

The declaration half runs everywhere; the browser half is skipped when the
worker isn't built, and runs in CI's `contract` job, which builds it.
"""

from pathlib import Path

import pytest

from verity.agents.interaction import (
    FIXTURES_DIR,
    run_contracts_on_artifact,
    verify_contract_fixtures,
)
from verity.models.schemas import WidgetInventory
from verity.rulepacks import load_contracts

REPO = Path(__file__).resolve().parents[2]
WORKER_JS = REPO / "node-worker" / "dist" / "rpc" / "server.js"

needs_worker = pytest.mark.skipif(
    not WORKER_JS.exists(),
    reason="node worker not built (cd node-worker && npm run build)",
)


def test_every_shipped_contract_declares_fixtures_that_exist():
    for name, contract in load_contracts().items():
        assert contract.fixtures is not None, f"{name} ships without A9.4 fixtures"
        for rel in (contract.fixtures.pass_, contract.fixtures.fail):
            assert (FIXTURES_DIR / rel).exists(), f"{name}: {rel} does not exist"


def test_the_first_contracts_are_in_place():
    """Week 9's five: tablist (B, Week 4), A's disclosure and menu-button, B's dialog and combobox."""
    assert {"tablist", "disclosure", "menu-button", "dialog", "combobox"} <= set(load_contracts())


async def _client():
    from verity.orchestrator.rpc_client import RPCClient

    client = RPCClient(command=["node", str(WORKER_JS)], default_timeout=60.0)
    await client.start()
    return client


@needs_worker
@pytest.mark.asyncio
async def test_contract_fixture_gate():
    client = await _client()

    async def run_fixture(path: Path):
        render = await client.send_request("render", {"url": path.as_uri()})
        try:
            return await run_contracts_on_artifact(client.send_request, render["artifactId"])
        finally:
            await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})

    try:
        problems = await verify_contract_fixtures(run_fixture)
    finally:
        await client.stop()
    assert problems == [], "\n".join(problems)


@needs_worker
@pytest.mark.asyncio
async def test_inventory_round_trips_and_is_never_speculative():
    """A9.2: the payload validates, and only explicitly-authored widgets appear."""
    client = await _client()
    try:
        render = await client.send_request(
            "render", {"url": (FIXTURES_DIR / "apg" / "tablist-pass.html").as_uri()}
        )
        raw = await client.send_request("inventoryWidgets", {"artifactId": render["artifactId"]})
        await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
    finally:
        await client.stop()

    inv = WidgetInventory.model_validate(raw)
    roots = {w.root.selector: w for w in inv.widgets}
    # The tablist, and nothing for the plain #before/#after buttons, which
    # carry no aria-expanded/aria-haspopup and so claim no widget pattern.
    assert list(roots) == ["#tabs"]
    tl = roots["#tabs"]
    assert [t.selector for t in tl.items] == ["#tab-1", "#tab-2", "#tab-3"]
    assert {n.attributes.get("id") for n in tl.related} >= {"panel-1", "panel-2", "panel-3"}
    assert tl.items[1].tabindex == -1 and tl.items[1].attributes["aria-selected"] == "false"
