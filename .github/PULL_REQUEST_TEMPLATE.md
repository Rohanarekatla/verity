## What changed and why

<!-- One or two sentences. Link an issue if there is one. -->

## Which side does this touch?

- [ ] `node-worker/` (TypeScript)
- [ ] `verity/` (Python)
- [ ] Both — the shared RPC contract (`protocol.ts` / `schemas.py`) changed

## Checklist

- [ ] Tests pass locally (`node --test test/protocol.test.mjs` and/or `uv run pytest verity/tests/`)
- [ ] If the RPC contract changed, both sides were updated in this PR
- [ ] If this reverses or revises a documented decision, `docs/adr/` was updated
