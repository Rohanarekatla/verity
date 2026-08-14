# Running Verity locally

From a clean clone to a real audit. Two toolchains — Node drives the
browser, Python drives everything else — so both need installing once.

## Prerequisites

| | Version | Check |
|---|---|---|
| Node.js | 22+ | `node --version` |
| Python | 3.13+ | `python3 --version` |
| uv | any recent | `uv --version` |

`uv` manages the Python environment. If you don't have it:
`curl -LsSf https://astral.sh/uv/install.sh \| sh`

## First-time setup

```bash
git clone https://github.com/Rohanarekatla/verity.git
cd verity
```

**1 · Node worker** — installs deps, downloads Chromium, compiles TypeScript

Comments are on their own lines throughout this guide — pasting a
command with a trailing `# comment` makes tools like `npx` treat the
comment words as arguments.

```bash
cd ~/Desktop/verity/node-worker
npm install
npx playwright install chromium
npm run build
```

That downloads Chromium (~180 MB) once.

**2 · Python orchestrator** — from the repo root, not `node-worker/`

```bash
cd ~/Desktop/verity
uv sync
```

That's it. `uv sync` creates `.venv/` and installs the Python
dependencies.

## Run a scan

**Every command below runs from the repo root.** The CLI is invoked as
a module, so `verity/` has to be visible from your current directory —
running it from `node-worker/` fails with `No module named 'verity'`.

```bash
cd ~/Desktop/verity
uv run python -m verity.cli scan https://example.com
```

Against the bundled fixtures — a page with a deliberate contrast
failure, and its clean twin:

```bash
uv run python -m verity.cli scan "file://$(pwd)/data/fixtures/contrast-fail.html"
uv run python -m verity.cli scan "file://$(pwd)/data/fixtures/contrast-pass.html"
```

The failing one prints:

```
============================================================
 VERITY ACCESSIBILITY AUDIT REPORT
============================================================
 Target URL     : file:///…/contrast-fail.html
 WCAG Standard  : WCAG2.2-AA
 Total Findings : 1
------------------------------------------------------------
 FINDINGS SUMMARY:
  1. [SERIOUS] SC 1.4.3 - Elements must meet minimum color contrast…
     Selector: #low-contrast-text
============================================================
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | No authoritative findings — or the scan found only non-gating ones |
| `1` | Authoritative findings exist, **or** the scan itself failed |

This is what makes it usable in CI. Only `AUTHORITATIVE` findings gate;
AI-assisted and needs-review annotate but never fail a build.

### Options

```bash
uv run python -m verity.cli scan <url> --output report.json
uv run python -m verity.cli scan <url> --timeout 60
uv run python -m verity.cli scan --help
```

`--output` writes the full `AuditReport` as JSON. `--timeout` sets the
per-RPC-call budget in seconds.

## Run the tests

Node — 15 protocol tests plus 4 browser tests:

```bash
cd ~/Desktop/verity/node-worker
npm test
```

Python — schemas, RPC client, CLI, injectors:

```bash
cd ~/Desktop/verity
uv run pytest verity/tests/
```

## Look under the hood

All from the repo root.

Talk to the worker by hand — stderr gets the log line, stdout gets the
protocol frame:

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | node node-worker/dist/rpc/server.js
```

The full render → runAxe walkthrough, every message printed:

```bash
python3 node-worker/contract/reference_client.py
```

Verbose worker logs (stderr only — stdout stays protocol-clean):

```bash
VERITY_LOG_LEVEL=debug uv run python -m verity.cli scan https://example.com
```

Rendered artifacts land in `.verity/cache/<sha256>/` — the DOM,
accessibility tree, computed styles, a full-page screenshot, and the
network log for every page scanned. The directory name is the content
hash, so re-scanning an unchanged page lands in the same place.

```bash
ls .verity/cache/*/
```

## Troubleshooting

**`Node worker not built: … is missing`**
The TypeScript wasn't compiled. `cd node-worker && npm run build`

**`Executable doesn't exist at …/chrome-mac/…`**
Chromium isn't installed. `cd node-worker && npx playwright install chromium`

**`No module named 'verity'`**
You're in the wrong directory — almost always `node-worker/`. Run
`cd ~/Desktop/verity` first. The CLI is invoked as a module, so `verity/`
must be visible from the current directory.

**`pytest: file or directory not found: verity/tests/`**
Same cause. `cd ~/Desktop/verity` first.

**`npx: Invalid installation targets: '#', 'one-time:', …`**
A `#` comment got pasted along with the command. Paste only the command
line.

**Scan hangs on a heavy page**
`render` has a 120s budget and `runAxe` 60s; both return a timeout error
rather than hanging forever. Raise with `--timeout` if a page genuinely
needs longer.

**`file://` URL finds nothing**
Use an absolute path — `file://$(pwd)/data/fixtures/contrast-fail.html`,
not a relative one.

## What it does and doesn't check today

Reports only findings that map to a **WCAG success criterion**. axe's
`best-practice` rules (`region`, `landmark-one-main`) are excluded from
the conformance report and logged instead — they're real observations,
but they are not WCAG conformance failures, and reporting them as such
would be a false positive.

Not built yet: contrast-over-image adjudication, keyboard/APG testing,
the vision agents, calibration, waivers, SARIF output, and the GitHub
Action. See [`docs/execution-plan.md`](docs/execution-plan.md).

## How it works

[`node-worker/ARCHITECTURE.md`](node-worker/ARCHITECTURE.md) — every
file mapped onto the path a single request takes, with diagrams.
