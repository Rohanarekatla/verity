# Ownership Proposal — WITHDRAWN, with two surviving items

> **Status: the main proposal is withdrawn.** It was written after
> reading only Weeks 1–3 of the Execution Plan. Having now read all 20
> weeks, its central premise was **false**. Recording the error here
> rather than deleting it, because the reasoning is instructive.

## What the withdrawn proposal claimed

> *"Every resume-critical module is Track B. Engineer A finishes having
> built the systems half of an ML project."*

**That is wrong.** Reading the full plan, Engineer A already owns:

| Week | A's task | Why it matters |
|---|---|---|
| W11 | **A11.1 — the schema linter**: rejects any required closed-vocabulary judgment field lacking an escape value | This *is* the fabrication-trap defence. It's the enforcement mechanism behind ADR-0008, the ADR the plan calls "most likely to be questioned by an outside reader" |
| W11 | A11.2/A11.3 — deterministic alt heuristics, decorative-image detection | The "run cheap deterministic checks before invoking a model" pattern |
| W12 | **A12.1–A12.4 — all of `verity/calibration/`**: isotonic regression, conformal prediction, three-bucket presentation, drift detection | The single rarest module in the project. It is entirely A's, in Python |
| W14 | **A14.1–A14.3 — ~15 fault injectors, the injection-verification pass, the prevalence-weighted corpus generator** | The eval harness's ground truth. *"Red flag if the candidate doesn't start with evals"* |
| W16 | A16.1–A16.3 — the ACR generator, honest labelling of untested criteria | Buyer-facing compliance artifact |
| W15 | A15.1–A15.3 — ACT runner, honest `cantTell` mapping | W3C conformance credibility |

Plus, across the plan: selector normalisation and JSON-Schema→TypeScript
codegen with a CI drift check (W6), stable finding signatures and
baseline storage (W7), the GitHub Action (W8), the APG contract runner
and its fixture CI gate (W9), the State Explorer (W13), bounded and
authenticated crawling (W17).

**Track A is not the browser track.** It is the browser track *plus*
calibration, the eval corpus, schema enforcement, and report
generation. The plan's rotation table (§1.4) is doing exactly the job
it claims to.

## Why the error happened — worth noting

I extrapolated a 20-week ownership distribution from three weeks of
data, and the first three weeks are the *least* representative: Phase 1
is deliberately browser-heavy because the browser skeleton is the
prerequisite for everything else. The AI-heavy A tasks all live in
Phases 3–4.

Practical lesson for the project: **the same failure mode applies to
gate decisions.** Judging a trend from the first available slice is how
the Week 2 precision bar gets rationalised after the fact. That is why
the plan insists the bar is written down on Monday.

## What Engineer A's Python ramp actually looks like

| When | Exposure |
|---|---|
| Now → W10 | Shared Monday block, explain-to-approve reviews, Sunday teach-back. **Continuous, and none of it is currently running** |
| W3 | Hand-implement the relative-luminance function from spec (both engineers, must agree to 6 dp) |
| W6 | JSON Schema → TypeScript codegen and the CI drift check |
| W9 | Rotation #2 — calibration ownership transfers B → A |
| **W11–W12** | **First substantial Python ownership: schema linter, then all of `verity/calibration/`** |
| W14 | Full injector set + prevalence-weighted corpus |
| W16 | Rotation #4 — report generation, ACR generator |

The answer to *"when do I get Track B work"* is **Week 11–12**, not
Week 9 and not Week 25. The gap is real but it is ten weeks of
deliberate sequencing, not neglect — you cannot calibrate before there
are model outputs to calibrate against, and those don't exist until
Week 11.

## What survives — two genuinely unscheduled items

Both are absent from the Execution Plan, both serve the AI/agentic
goal, and both are still worth considering.

### 1 · Agentless remediation baseline — ~2 weeks

A one-shot localise → propose-diff → apply-in-sandbox → re-check
pipeline. No Planner, no Critic.

The Research Brief's guidance is to build this **before** any agent
loop and keep the loop only if it measurably beats the baseline — so
it is required work under either decision, and it is the cheaper half.
It also yields the defensible interview answer: *"multi-agent rarely
wins on tightly-coupled tasks; I benchmarked mine against an agentless
baseline."*

Note this is genuinely new scope: the Execution Plan is
**detection-only**. Remediation ("suggest diffs, never auto-merge")
appears in the Bible's product description but is scheduled nowhere.

### 2 · MCP server adapter — ~2–3 days

`node-worker` already speaks JSON-RPC 2.0 over newline-framed stdio,
which *is* the MCP stdio transport; ADR-0001 cites MCP as the reason
for that choice. Adding `initialize`, `tools/list`, and `tools/call`
over the existing `render`/`runAxe` makes Verity usable as a tool by
any MCP client. Highest signal-per-hour available on this project.

### Where the weeks come from — the honest constraint

Weeks 18–19 are the **only** buffer. The plan is explicit: *"Do not
spend this buffer on scope."* Together these two additions are ~2.5
weeks against a 2-week buffer.

**Decide at the Week 9 gate (25 Oct)**, with three phases of evidence
on whether the schedule is holding — not now. If Phases 1–3 land on
time, take the MCP adapter first (it's days, not weeks) and treat the
agentless baseline as a stretch.

## What needs no decision at all

The three knowledge-parity rituals are specified in the plan and are
**not running**. They cost nothing, need nobody's agreement, and are
the actual answer to "I want to learn both sides":

1. **Monday shared block** — 60 minutes, identical material, both
   engineers. Weeks 11, 12, and 14 have shared blocks on the
   fabrication trap, calibration, and prevalence weighting — the exact
   topics in question.
2. **Explain-to-approve review** — approving Nikhil's Python requires
   writing three lines describing its mechanism in your own words.
3. **Sunday teach-back** — you write the notes on *his* week, into
   `docs/teachback/YYYY-WW.md`. What you can't write is next week's
   gap list.

Start Monday 17 August.
