# Verity

**An accessibility scanner that won't cry wolf.** Verity runs `axe-core`, then
*resolves* the checks axe leaves as "needs review" — most importantly **text
over background images** — by sampling the actual rendered pixels and doing the
WCAG contrast math. You get an **authoritative** pass/fail where other tools
shrug, and an honest "can't tell" where the answer truly is ambiguous. It never
invents a finding to look thorough.

```
 VERITY ACCESSIBILITY AUDIT REPORT
 Target URL     : https://example.com
 WCAG Standard  : WCAG2.2-AA
 Failures       : 1
 Needs review   : 0
------------------------------------------------------------
 FAILURES (gate the build):
  1. [SERIOUS] SC 1.4.3 - Contrast between foreground and background is
     below the WCAG 2 AA minimum ratio
     Selector: #low-contrast-text
```

*Failures gate your build (exit 1); items Verity genuinely can't decide are
listed separately as "needs review" and never gate.*

[![CI](https://github.com/Rohanarekatla/verity/actions/workflows/ci.yml/badge.svg)](https://github.com/Rohanarekatla/verity/actions/workflows/ci.yml)
[![License: MPL-2.0](https://img.shields.io/badge/License-MPL--2.0-brightgreen.svg)](LICENSE)

---

## Why another a11y scanner?

Automated tools catch only [30–40% of WCAG issues](https://www.deque.com/automated-accessibility-testing-coverage/),
and a big chunk of what they *do* report on visually rich pages is **noise**:

| The problem | axe-core / Lighthouse / Pa11y | Verity |
|---|---|---|
| **Text over a hero image** | Returned as `incomplete` / "needs review" — you check it by hand. Pa11y has historically surfaced these as hard errors. | Samples the rendered pixels, computes the real ratio, returns an **authoritative** pass or fail. |
| **The 3.0–4.5:1 grey zone** (large vs normal text) | Guessed or flagged | Reported as **`cantTell`**, never guessed — a wrong finding is worse than a missing one |
| **"Needs review" items** | Mixed into the error count, so a clean page can look broken | Split out: **failures gate your build, review items never do** |
| **A model in the loop** | — | Any model is a *localiser* only; its output must clear a deterministic check before it becomes a finding |

If you've ever had a CI build go red over a contrast "error" on a background
image that was actually fine, Verity is built for exactly that.

## Install & run

**Prerequisites:** Node 22+, Python 3.13+, and [`uv`](https://docs.astral.sh/uv/)
(`curl -LsSf https://astral.sh/uv/install.sh | sh`).

```bash
git clone https://github.com/Rohanarekatla/verity.git
cd verity

# 1. Node worker — browser + axe-core engine (downloads Chromium once, ~180 MB)
cd node-worker && npm install && npx playwright install chromium && npm run build && cd ..

# 2. Python orchestrator
uv sync

# 3. Scan a page
uv run python -m verity.cli scan https://example.com
```

Verity exits **1** when an authoritative failure exists and **0** when the page
is clean — so it drops straight into CI. The first scan is slower while Chromium
warms up; subsequent scans are quick.

Full walkthrough: [RUNNING.md](RUNNING.md).

## What it checks today

| Capability | State |
|---|---|
| `axe-core` full ruleset + WCAG 2.2 criterion mapping (`best-practice` excluded) | ✅ |
| **Contrast-over-image adjudication** — `incomplete` resolved from sampled pixels | ✅ |
| Honest `cantTell` for the 3.0–4.5:1 band (no guessing) | ✅ |
| Keyboard traversal → SC 2.1.1 / 2.1.2 / 2.4.3 / 2.4.7 | ✅ |
| APG interaction contracts for ARIA widgets | ✅ |
| Dedup, waivers, per-scan latency in the report | ✅ |
| **SARIF** (GitHub code-scanning), JUnit, VPAT output | ✅ |
| **GitHub Action** + content-addressed baselines + build gating | ✅ |
| Configurable gating policy (`fail_on` / `annotate_on`) | ✅ |

### Research direction: agent accessibility

Verity also hosts an experimental benchmark for a newer question: **do WCAG
defects break AI web agents?** It measures whether an agent's task-success rate
drops on pages with injected accessibility defects, and exposes Verity's checks
over an MCP server so a fix loop can be verifier-gated. This is early and gated
behind model keys/budget — see [`docs/agentbench/`](docs/agentbench/). The
scanner above is the stable, usable product.

## How it works

A **polyglot system**: a Python orchestrator (ML, calibration, trust machinery,
report generation) drives a long-lived Node.js worker (Playwright + `axe-core`)
over JSON-RPC 2.0 on stdio. Python has the ML ecosystem; Node has the only
trustworthy `axe-core`. Neither does the other's job. Rationale in
[`docs/adr/0001-polyglot-json-rpc-over-stdio.md`](docs/adr/0001-polyglot-json-rpc-over-stdio.md).

```
node-worker/   TypeScript: Chromium, axe-core, accname, contrast math (authoritative engines)
verity/        Python: orchestration, adjudication, calibration, SARIF/VPAT/JUnit reports
data/          WCAG criteria, APG interaction contracts, test fixtures
eval/          Fault-injection harness + frozen accuracy baselines
action/        GitHub Action wrapper
docs/adr/      Architecture Decision Records
```

Each directory has its own `README.md`; the Node request flow is walked
end-to-end in [`node-worker/ARCHITECTURE.md`](node-worker/ARCHITECTURE.md).

## Contributing

Issues and PRs welcome. Start with [CONTRIBUTING.md](CONTRIBUTING.md) (the shared
RPC contract and PR conventions) and [RUNNING.md](RUNNING.md). The one rule worth
knowing up front: a change to what the worker can do touches **both**
`node-worker/rpc/protocol.ts` and `verity/models/schemas.py` in the same PR —
they're two views of one interface, and CI runs a cross-language contract check
to keep them honest.

## License

[MPL-2.0](LICENSE).
