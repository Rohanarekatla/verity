# Verity (Project-V)

Verity is an accessibility conformance engine: a Python orchestrator (ML,
trust machinery) drives a long-lived Node.js worker (Playwright, axe-core)
over JSON-RPC 2.0 on stdio. It's a polyglot system — Python owns the ML and
orchestration ecosystem, Node owns the browser.

## Layout

```
.
├── node-worker/            # TypeScript: JSON-RPC worker over stdio
│   ├── src/
│   │   ├── rpc/            # protocol, framing, dispatcher, server
│   │   └── handlers/       # method implementations (ping, render, runAxe)
│   ├── test/                # protocol boundary tests (15 cases)
│   ├── contract/            # Python reference client — proves the wire format
│   └── A1.1-explained.md    # full design rationale, error codes, interview notes
└── orchestrator/            # Python side (in progress)
```

## Getting started

```bash
git clone https://github.com/Rohanarekatla/Project-V.git
cd Project-V/node-worker
npm install
npm run build

node --test test/protocol.test.mjs     # should be 15/15
python3 contract/reference_client.py   # proves Python <-> Node contract
```

## The contract

- **Node** (`node-worker/`) owns the browser: Playwright + axe-core.
- **Python** (`orchestrator/`) owns orchestration, ML, and the trust layer.
- They talk over **JSON-RPC 2.0**, one JSON object per line, on stdio.
- The interface is `node-worker/src/rpc/protocol.ts` — if you change it, the
  other side breaks. Coordinate before pushing.

Full rationale for every design decision (subprocess vs HTTP, framing,
error codes, timeouts) is in
[`node-worker/A1.1-explained.md`](node-worker/A1.1-explained.md).

## Working here

- Each engineer works in their own top-level folder (`node-worker/` vs
  `orchestrator/`) so changes rarely collide.
- `node_modules/`, `dist/`, and Python build artifacts are gitignored —
  never commit them.
- Before pushing a change to `src/rpc/protocol.ts`, ping the other side —
  it's the shared interface both languages depend on.
