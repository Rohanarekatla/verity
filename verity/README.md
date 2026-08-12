# verity/

The Python side: orchestration, data models, ML agents, calibration,
and report generation. Talks to [`node-worker/`](../node-worker/) over
JSON-RPC — see [ADR 0001](../docs/adr/0001-polyglot-json-rpc-over-stdio.md)
for why.

| Path | Purpose |
|---|---|
| [`models/`](models/) | Pydantic schemas — the single source of truth for data shapes, mirrored into TypeScript for the Node side |
| [`orchestrator/`](orchestrator/) | Spawns and drives the Node worker; the single-URL scan pipeline |
| [`agents/`](agents/) | ML workers — vision, audio, contrast-over-image, and the validator that dedups and stamps provenance |
| [`calibration/`](calibration/) | Confidence calibration (isotonic regression, conformal prediction) |
| [`report/`](report/) | Output generators — SARIF, VPAT/ACR, JUnit |
| `cli.py` | `verity scan <url>` entrypoint |
| [`tests/`](tests/) | pytest suite for everything above |

```bash
uv sync
uv run pytest verity/tests/
```
