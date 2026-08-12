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
