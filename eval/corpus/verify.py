"""
A2.3 (rigorous half) — rendered verification of the Spike A corpus.

`build.py` verifies each injection *structurally*: exactly one element
changed, only the allowed attributes. That is fast and catches
corrupted transforms, but it cannot tell whether the defect actually
*manifests* — an injection into a hidden accordion panel or a closed
dialog changes the DOM correctly yet produces no accessibility barrier,
because a hidden element has none. Labelling such a case
`expected_outcome: fail` is silently-wrong ground truth: it would count
against precision for a defect that genuinely is not there.

This pass renders both halves of every pair through the real worker and
keeps the `fail` label only when the injected defect shows up as a new
finding of the expected success criterion. It is slow (a browser render
per half) so it is a separate, opt-in step:

    python -m eval.corpus.verify

It reuses one worker and one browser across all cases, and rewrites
labels.json in place with a `detected` field per case plus a summary.
Undetected cases are marked `expected_outcome: "no_manifest"` rather
than deleted, so the reason a case was dropped stays inspectable.

The three Week 1 injectors all target deterministically-detectable
criteria (1.1.1 presence, 1.3.1 label association, 1.4.3 contrast on
solid backgrounds), so "axe detects it when visible" is a sound
invariant *for this corpus*. It would not be for the vision-only
injectors (contrast-over-image, alt-meaningfulness) added later — those
are exactly the cases axe declines to judge — so this check stays scoped
to the deterministic injector set.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

from verity.orchestrator.rpc_client import RPCClient
from verity.orchestrator.main import extract_sc_id

HERE = Path(__file__).resolve().parent
LABELS = HERE / "generated" / "labels.json"

WORKER_CMD = [
    "node",
    str(Path(__file__).resolve().parents[2] / "node-worker" / "dist" / "rpc" / "server.js"),
]


def _write_labels(labels: dict) -> None:
    """Atomic write so an interrupt mid-write can't corrupt labels.json."""
    tmp = LABELS.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(labels, indent=2), encoding="utf-8")
    tmp.replace(LABELS)


async def sc_counts(client: RPCClient, html_path: Path) -> Counter:
    """Render + runAxe one file, return a Counter of WCAG SC ids in violations."""
    render = await client.send_request("render", {"url": html_path.resolve().as_uri()})
    axe = await client.send_request("runAxe", {"artifactId": render["artifactId"]})
    counts: Counter = Counter()
    for v in axe.get("violations", []):
        sc = extract_sc_id(v.get("tags", []))
        if sc:
            counts[sc] += 1
    return counts


async def run() -> int:
    if not LABELS.exists():
        print("no labels.json — run `python -m eval.corpus.build` first", file=sys.stderr)
        return 1

    labels = json.loads(LABELS.read_text())
    cases = labels["cases"]
    print(f"verifying {len(cases)} cases through the real worker...")

    client = RPCClient(command=WORKER_CMD, default_timeout=60.0)
    await client.start()

    detected = 0
    no_manifest = 0
    try:
        for i, c in enumerate(cases, 1):
            # Any acceptable criterion manifesting counts. axe maps a broken
            # label to 4.1.2, not the 1.3.1 the injector is named for, so a
            # single-SC check silently zeroed out every detach_label case.
            acceptable = c.get("acceptable_sc", [c["expected_sc"]])
            clean = await sc_counts(client, HERE / c["clean_path"])
            bad = await sc_counts(client, HERE / c["injected_path"])
            delta = max(bad[sc] - clean[sc] for sc in acceptable)

            c["detected"] = delta > 0
            c["detected_delta"] = delta
            if delta > 0:
                detected += 1
            else:
                c["expected_outcome"] = "no_manifest"
                no_manifest += 1

            if i % 20 == 0:
                # Checkpoint: a 7-minute job should not lose everything if
                # interrupted. Written atomically so a kill mid-write can't
                # corrupt the labels.
                _write_labels(labels)
                print(f"  {i}/{len(cases)} ({detected} detected, {no_manifest} no-manifest)", flush=True)
    finally:
        await client.stop()

    labels["verified"] = True
    labels["detected_cases"] = detected
    labels["no_manifest_cases"] = no_manifest
    _write_labels(labels)

    print(f"\n  detected     : {detected}")
    print(f"  no-manifest  : {no_manifest}  (hidden / non-rendering, downgraded)")
    print(f"  usable cases : {detected}")
    return 0 if detected else 1


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
