"""
Week 9 gate — run the APG contracts against the live W3C reference
implementations and print every failure and cantTell.

The gate is "all APG reference implementations pass; zero false alarms". The
pass fixtures in data/fixtures/apg/ are ours; these pages are the APG's own,
and they exercise variants ours do not (action buttons inside tabs,
aria-activedescendant menus). Needs network access, so it is a script, not a
CI test. Results are recorded in docs/measurements/apg-reference-implementations.md.

    cd node-worker && npm run build && cd ..
    uv run python eval/apg_reference_check.py
"""

import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from verity.agents.interaction import run_contracts_on_artifact  # noqa: E402
from verity.orchestrator.rpc_client import RPCClient  # noqa: E402

BASE = "https://www.w3.org/WAI/ARIA/apg/patterns/"
REFERENCE_PAGES = [
    "tabs/examples/tabs-automatic/",
    "tabs/examples/tabs-manual/",
    "tabs/examples/tabs-actions/",
    "disclosure/examples/disclosure-faq/",
    "disclosure/examples/disclosure-image-description/",
    "menu-button/examples/menu-button-actions/",
    "menu-button/examples/menu-button-actions-active-descendant/",
    "menu-button/examples/menu-button-links/",
]


async def main() -> int:
    client = RPCClient(
        command=["node", str(REPO / "node-worker" / "dist" / "rpc" / "server.js")],
        default_timeout=120.0,
    )
    await client.start()
    false_alarms = 0
    try:
        for page in REFERENCE_PAGES:
            render = await client.send_request("render", {"url": BASE + page})
            try:
                run = await run_contracts_on_artifact(client.send_request, render["artifactId"])
            finally:
                await client.send_request("releaseArtifact", {"artifactId": render["artifactId"]})
            matched = {k: v for k, v in run.widgets_matched.items() if v}
            print(f"== {page} {matched}")
            for r in run.results:
                if r.outcome in ("fail", "cantTell"):
                    false_alarms += r.outcome == "fail"
                    print(f"   {r.widget:30.30} {r.contract:11} {r.assertion_id:34} {r.outcome:8} {r.detail}")
    finally:
        await client.stop()
    print(f"\n{false_alarms} failure(s) on reference implementations (gate requires 0)")
    return 1 if false_alarms else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
