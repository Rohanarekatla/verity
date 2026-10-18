# Nikhil — action item BC-A1: wire `traverseTabOrder` into `scan_url()`

**From Rohan. Priority: #1 (highest-ROI item in the repo).**
Plan reference: `docs/execution-plan.md` → Best-in-class backlog → BC-A1.

This is a ~10–15 line integration on your side, and it's the one that turns the
entire keyboard wedge from "built and tested" into "actually shows up in a
scan". Everything below already exists — the worker method, the schema, the
four judges, the retry policy. Nothing new has to be written; it has to be
*called*.

---

## The situation, stated plainly

A `verity scan <url>` today emits **zero keyboard findings**. The traversal
method ships (A4.1–A4.3), the `TraversalResult` contract is in
`verity-schema.json` and the generated TS mirror, and your own
`verity/agents/keyboard.py` turns one `TraversalResult` into four findings
(SC 2.1.1 / 2.1.2 / 2.4.3 / 2.4.7) — but `scan_url()` never calls the worker
method, so none of it runs on a real page. The differentiator is dark.

You said in Week 4: *"the moment `traverseTabOrder` exists, I'll wire it behind
the same graceful-fallback guard the contrast adjudicator uses."* It exists.

## What my side gives you (all merged, nothing pending)

- **RPC method:** `traverseTabOrder`, params
  `{ "artifactId": <id>, "cyclesRequested"?: int, "maxPresses"?: int, "measureFocusVisible"?: bool }`.
  Returns a JSON object matching `TraversalResult`.
- **It peeks the live page**, exactly like `sampleRegion` — so call it on the
  same `artifact_id` the render produced, before `releaseArtifact`.
- **Verified round-trip:** `verity/tests/test_traverse.py` already drives the
  real worker → validates the payload as `TraversalResult`. The contract holds.

## Where it goes

`verity/orchestrator/main.py`, in `scan_url()`, right after the
incomplete-contrast loop and before the `finally` that releases the artifact.
Mirror `_adjudicate_incomplete_contrast`'s graceful-fallback shape: a worker
too old to know the method, a timeout, a payload that doesn't validate — none
of those are evidence of a keyboard defect, so none may produce a finding.
Silence here means "we couldn't check", and that's fine — it just means no
keyboard findings this run, never a fabricated one.

## The wiring (sketch — adjust names to taste)

```python
from verity.agents.keyboard import resolve_with_retries   # B4.4 — your own
from verity.models.schemas import TraversalResult

async def _run_keyboard(rpc_call, artifact_id, page_state_hash) -> list[Finding]:
    """BC-A1 — traverse the page's tab order and map it to SC 2.1.1/2.1.2/
    2.4.3/2.4.7. No finding is produced if the traversal can't run."""
    async def run_traversal() -> TraversalResult:
        raw = await rpc_call(
            "traverseTabOrder",
            {"artifactId": artifact_id, "measureFocusVisible": True},
        )
        return TraversalResult.model_validate(raw)

    try:
        findings, _attempts = await resolve_with_retries(run_traversal, page_state_hash)
        return findings
    except Exception as exc:
        logger.info(
            "keyboard traversal unavailable (%s); no keyboard findings this run.",
            exc.__class__.__name__,
        )
        return []
```

Then in `scan_url`, after the contrast loop:

```python
keyboard_findings = await _run_keyboard(rpc_call, artifact_id, content_hash)
all_findings.extend(keyboard_findings)
```

`resolve_with_retries` already handles B4.2 (indeterminate) and B4.4 (re-run
while indeterminate, capped, never escalating) — you wrote it. If you'd rather
not retry inside a scan, call `map_traversal_to_findings(result, content_hash)`
directly instead; both are in `keyboard.py`.

## The one decision worth 60 seconds

**`measureFocusVisible`.** The sketch passes `True`. If you leave it off (the
default), every `TabStop.focus_visible` comes back `None` ("not measured"), and
`judge_focus_visible` correctly returns **`indeterminate`** for SC 2.4.7 on
*every* page — so 2.4.7 is perpetually needs-review and never a real verdict.
Passing `True` runs the focused-vs-baseline computed-style diff per stop and
gives real pass/fail, at the cost of some extra time per scan.

My recommendation: **`True`** — 2.4.7 is a headline keyboard criterion and the
whole point of A4.3 was to make it measurable. But it's your call on the
latency trade-off, and it's a one-word change either way. Worth deciding
together rather than one of us assuming.

## Verification (so we know it works, not just compiles)

There are ready-made fixtures from Week 4 — reuse them:

- `data/fixtures/keyboard-tablist.html` — a correct APG tablist. A scan must
  produce **no SC 2.1.1 barrier finding** (the five roving tabs are
  arrow-navigable). This is the zero-false-alarms half of the Week 4 gate,
  now at the scan level.
- `data/fixtures/keyboard-trap.html` — a scan must produce an SC 2.1.2
  **fail**.
- `data/fixtures/keyboard-positive-tabindex.html` — an SC 2.4.3 **fail**.

A `verity/tests/test_main.py`-style integration test (real worker, like the
Week 1 gate guard) over those three closes the loop: it proves keyboard
findings reach the report, and that a clean widget stays quiet.

## Why this is #1

Everything else in the best-in-class backlog is expansion. This is not — it's
the gap between a differentiator we already paid for and a differentiator that
exists in a user's scan output. Until this lands, "Verity does keyboard
testing" is true in the test suite and false on the command line.

---

Ping me if anything in `TraversalResult` is awkward to consume from the
orchestrator — same offer as Week 4, I'd rather change the shape now than have
the two sides drift.
