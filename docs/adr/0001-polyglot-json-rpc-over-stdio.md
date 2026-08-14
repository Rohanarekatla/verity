# ADR 0001: Polyglot architecture — Python orchestrator, Node worker, JSON-RPC 2.0 over stdio

**Status:** Accepted

## Context

Verity needs two things that don't live in the same ecosystem:

- The browser automation and accessibility rules engine. `axe-core` is
  JavaScript and runs inside a browser page; there is no equivalent
  Python implementation worth trusting over the reference one.
- The orchestration, ML, and trust machinery (calibration, provenance,
  report generation) — Python has the ecosystem for this.

Neither language can do the other's job well, so this has to be a
polyglot system. The question is how the two processes talk to each
other.

## Decision

A Python orchestrator spawns a **long-lived Node.js worker as a
subprocess** and drives it with **JSON-RPC 2.0, one JSON object per
line, over stdio**.

### Why a subprocess, not an HTTP microservice

| Option | Why not |
|---|---|
| HTTP microservice | Needs a port, health checks, and a deployment story. Verity is a CLI tool run locally and in CI — asking users to run two services is a non-starter. |
| Rewrite axe-core in Python | Thousands of hours reimplementing the reference implementation the industry trusts. |
| Spawn Node per request | Node startup (~50ms) plus browser launch (~500ms) paid on every call. On a multi-page crawl with several calls per page, that's minutes of pure overhead. |
| **Long-lived subprocess over stdio** | One process, one browser launch, no ports, no network, no auth — the OS provides the transport for free. |

The browser is expensive to start and cheap to reuse; that's the whole
reason for the design.

### Why JSON-RPC 2.0, not a custom protocol


{"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}}

{"jsonrpc": "2.0", "id": 1, "result": {"pong": true, "workerVersion": "0.1.0", "protocolVersion": 1}}

-Small, stable, well-documented spec with defined error semantics —
  the part people get wrong when rolling their own.
- It's the same shape used by the Language Server Protocol and MCP:
  editor/agent driving a subprocess over stdio. Following a proven
  pattern beats inventing one.
- We implement a deliberate subset: no batching, no server-initiated
  requests. Neither is needed here.

### Framing: newline-delimited, not length-prefixed

stdin/stdout are byte streams, not message streams — one `data` event
does not equal one JSON-RPC message. We frame messages by newline
(`JSON.stringify` escapes real newlines inside strings, so a raw
`0x0A` byte can only ever be our delimiter), buffering partial lines
across chunks.

The alternative — LSP-style `Content-Length: N\r\n\r\n<N bytes>`
headers — is more robust (no delimiter can appear in the payload at
all) but more code to implement on both sides. Newline-delimited JSON
is the right tradeoff when we control both ends of the pipe.

### Error containment: the dispatcher never throws

Every RPC call resolves to either a result or a structured error body
— never an unhandled rejection. A hang is worse than a failure: if a
handler throws and nothing is sent back, the Python client awaits a
future that never settles, and the failure surfaces minutes later with
no stack trace. Per-method timeouts (`ping` 5s, `render` 120s, `runAxe`
60s) back this up so one hung page can't wedge the whole worker.

## Consequences

- The wire contract lives in `node-worker/rpc/protocol.ts` and its
  Python mirror in `verity/models/schemas.py`. Both are the shared
  interface — see [CONTRIBUTING.md](../../CONTRIBUTING.md#the-shared-contract).
- `stdout` on the Node side is protocol-only; every log line goes to
  stderr, and a stray `console.log` from a dependency would otherwise
  corrupt the stream.
- Truncated writes on process exit are a known failure mode with piped
  stdout — pending writes must be drained before `process.exit()`.

Full write-up of the framing bug this surfaced during Week 1
implementation: [`node-worker/A1.1-explained.md`](../../node-worker/A1.1-explained.md).
