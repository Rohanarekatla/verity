# Contributing to Verity

Verity is a polyglot project: a Python orchestrator drives a Node.js
worker over JSON-RPC 2.0. Most contributions touch exactly one side.
This doc covers how to get either side running, and the conventions
that keep the two sides from drifting apart.

## Project layout

See the [root README](README.md#layout) for the full directory map.
Each directory has its own `README.md` describing what belongs there
and who's expected to own it.

## Setting up

### Node worker (`node-worker/`)

New to this side? [`node-worker/ARCHITECTURE.md`](node-worker/ARCHITECTURE.md)
maps every file onto the path a request takes.

```bash
cd node-worker
npm install
npm run build
node --test test/protocol.test.mjs
```

### Python orchestrator (everything under `verity/`)

```bash
uv sync
uv run pytest verity/tests/
```

### Both together (proves the cross-language contract)

```bash
cd node-worker && npm run build && cd ..
python3 node-worker/contract/reference_client.py
```

## The shared contract

[`node-worker/rpc/protocol.ts`](node-worker/rpc/protocol.ts) and
[`verity/models/schemas.py`](verity/models/schemas.py) are the two
halves of the interface between the languages. If you change either
one:

1. Open an issue or PR that clearly states which field/method changed
   and why.
2. Update both sides in the same PR where possible — a protocol change
   that only lands on one side breaks the other silently.
3. Add or update the boundary tests (`node-worker/test/` or
   `verity/tests/`) that exercise the change.

See [`docs/adr/`](docs/adr/) for the design decisions already made
about this boundary (framing, error codes, why stdio instead of HTTP)
before proposing an alternative.

## Commit and PR conventions

- Commit messages: short imperative summary line, blank line, then the
  *why* if it's not obvious from the diff.
- One logical change per PR. A protocol change and an unrelated
  refactor should be two PRs.
- Run the relevant test suite (Node, Python, or both) before opening a
  PR — CI runs the same checks and will fail otherwise.

## Architecture Decision Records

Non-obvious design decisions (why a subprocess instead of an HTTP
service, why provenance has no default, why waivers hash on a stable
signature) get written up as an ADR in `docs/adr/`. If you're about to
revisit one of these decisions, read the existing ADR first — it
usually records the alternative you're about to propose and why it was
rejected at the time.

## Code of conduct

Be direct, be kind, assume good faith. Disagreements about design are
expected and welcome; keep them about the work.
