# verity/orchestrator/

- `rpc_client.py` — spawns the Node worker as an asyncio subprocess;
  handles stdio JSON-RPC calls, per-call timeouts, and clean shutdown.
- `main.py` — the single-URL execution pipeline: render → runAxe → map
  raw violations onto `Finding` models.

This is the Python half of the contract described in
[ADR 0001](../../docs/adr/0001-polyglot-json-rpc-over-stdio.md). If
you change how a call is made or times out, check
[`node-worker/src/rpc/dispatcher.ts`](../../node-worker/src/rpc/dispatcher.ts)
for the matching behavior on the other side.

## Known drift from the Node side (needs a Python-side fix)

`main.py`'s `scan_url()` currently calls a method named `"analyze"`,
which doesn't exist — the worker only registers `ping`, `render`, and
`runAxe` (see
[`node-worker/src/handlers/index.ts`](../../node-worker/src/handlers/index.ts)).
It should call `"runAxe"` with `{"artifactId": ...}`, where
`artifactId` comes from the `render` response.

It also reads `render_result.get("content_hash", ...)` as a flat
field. The real shape is nested — `render_result["page_state"]["content_hash"]`
— matching `RenderArtifact.page_state.content_hash` in
[`verity/models/schemas.py`](../models/schemas.py), since that model is
the source of truth for the shape (ADR 0001). `render`'s actual
response also includes an `artifactId` field alongside the
`RenderArtifact` fields — not part of the Pydantic model, but needed
to call `runAxe` against the same rendered page.

The `runAxe` result shape is `{url, timestamp, violations, passes,
incomplete, inapplicable}`, each a list of `{id, impact, tags,
description, help, helpUrl, selector, html, failureSummary}` — one
entry per affected node, not per rule. `map_raw_violation_to_finding()`
expects `wcag_id`, `selector`, and `details` keys that axe's raw output
doesn't produce under those names; that mapping will need adjusting
once this is wired up correctly.
