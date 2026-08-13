# Team Operating Doc

**This document is not the plan.** The plan lives in two source
documents held outside the repo:

| Document | Defines |
|---|---|
| *Verity — The Project Bible v1.0* | *what* is being built and *why* |
| *Verity — Execution Plan* (20 build weeks, 10 Aug 2026 → 10 Jan 2027) | *who* does what, *in which week*, and *how we know it's done* |
| *Multi-Agent Agentic AI Engineering in 2026 — Research Brief* | the evidence base for the (unscheduled) remediation layer |

This file is the in-repo operational companion: the rituals in a place
we'll actually see them, plus the live delta between the plan and the
repo. **Where this file and the Execution Plan disagree, the Execution
Plan wins.**

---

## 1. Team model

Two engineers, **Engineer A** and **Engineer B**. Assignment is **by
track, not by seniority** — either person can hold either track.

| Track | Primary domain | Stack |
|---|---|---|
| **A** | Browser, deterministic testing, CI surface | TypeScript, Node, Playwright, axe-core |
| **B** | Orchestration, ML, trust machinery, evaluation | Python, asyncio, Pydantic, MLX |

Currently: **Rohan = A**, **Nikhil = B**. Both tracks are load-bearing;
neither is a support role.

## 2. Knowledge parity protocol

> **The rule: at any point in the project, either engineer must be able
> to explain, run, and debug any component in the repository.**

This does not happen through good intentions. It happens through five
rituals with specific outputs.

### 2.1 Shared Learning Day — Mondays, no code

| Block | Duration | Who | Content |
|---|---|---|---|
| Shared | 60 min | Both, identical material | The core concept for the week |
| Track | 45 min | Each on their own track | Implementation-specific depth |

**The 48-hour rule:** anything studied Monday must appear in code by
Wednesday night. If it doesn't, it was the wrong topic for that week.

Each Learning Day names a **required artifact** — a written or coded
output. Both engineers produce it *independently*, then compare at the
Wednesday sync. Divergence is the earliest possible signal that the two
of us understand the problem differently.

### 2.2 Explain-to-approve code review

Every PR is reviewed by the other engineer. **Approval requires the
reviewer to write a three-line summary of what the code does, in their
own words, in the PR comment.**

Not "LGTM." Not a list of nitpicks. Three lines describing the
mechanism. If the reviewer can't write them, the PR isn't blocked — but
the author owes the reviewer a walkthrough before it merges.

### 2.3 Sunday teach-back — 30 minutes

Each engineer teaches the other what they built that week.

**The listener writes the notes, not the teacher.** Notes go into
[`docs/teachback/YYYY-WW.md`](teachback/), committed. A teacher writing
their own summary proves nothing. A listener producing coherent notes
proves transmission actually occurred.

### 2.4 Rotation at phase boundaries

At the end of each phase, **one module transfers ownership**. The
outgoing owner does not touch it for the following phase.

| Boundary | Module transferring | From → To |
|---|---|---|
| End of Phase 1 (W5) | Static/DOM Agent | A → B |
| End of Phase 2 (W9) | Confidence & calibration | B → A |
| End of Phase 3 (W13) | Interaction Agent | A → B |
| End of Phase 4 (W17) | Report generation | B → A |

Rotation is uncomfortable and slows the receiving engineer for about a
week. That is the price of eliminating single points of knowledge, and
it is far cheaper than discovering in month four that only one person
can debug the calibration layer.

> The full week-by-week schedule, with every A/B task and gate, is
> transcribed in [`execution-plan.md`](execution-plan.md).
>
> An earlier proposal to redistribute ownership has been
> [**withdrawn**](ownership-proposal.md) — it was based on a partial
> reading of the plan and its premise was false. Engineer A already
> owns calibration (W12), the schema linter (W11), the fault-injector
> set and prevalence-weighted corpus (W14), and report generation
> (W16). Two genuinely unscheduled items survive there for a decision
> at the W9 gate.

### 2.5 Bus-factor test — each phase gate

A 30-minute live exercise: A is handed a deliberately broken version of
a Track B component and must diagnose it unaided. Then the reverse.

**Failure is a documentation defect, not a personal one.** The fix is
to improve the docs and re-run the test the following week.

### 2.6 Decision log

Every non-obvious decision becomes an ADR in
[`docs/adr/NNNN-title.md`](adr/): Context → Decision → Consequences →
Alternatives rejected. **Both engineers sign every ADR.** If one of us
doesn't agree or doesn't understand it, it isn't ready to be an ADR.

## 3. Week shape

| Day | Block | Hrs each | Content |
|---|---|---|---|
| Mon | Learning Day | 1.75 | Shared 60m + track 45m. No code. |
| Tue | Execution | 2 | Track tasks |
| Wed | Execution + sync | 2 | Track tasks + 20-min mid-week sync |
| Thu | Execution | 2 | Track tasks |
| Fri | Review | 1 | Cross-review the other's open PRs |
| Sat | Main block | 4.5 | Heaviest task of the week |
| Sun | Main block + rituals | 3.75 | Finish + teach-back (30m) + gate check (30m) |

**Mid-week sync (Wed, 20 min, strictly timeboxed):**
1. Is anything blocked on the other track?
2. Has anything discovered this week invalidated an assumption in the Bible?
3. Is the gate still achievable by Sunday? If not, what gets cut *now*
   rather than Saturday night?

**Non-negotiables:** every week ends with a binary Gate (no partial
credit); every week has a testable Definition of Done ("works on my
machine" is not a DoD); the knowledge-parity protocol is not optional
overhead; when a gate fails twice, **cut scope** — never extend the
timeline.

---

## 4. Status delta — repo vs plan

*Last verified: Week 1, after the render/runAxe merge. Update this
section at each Sunday gate.*

### Week 1 — gate met, three items still open

The Week 1 gate is: *"A real production web page produces a correct
authoritative contrast finding **through the CLI**."*

| Task | Owner | Status |
|---|---|---|
| A1.1 `rpc/server.ts` — JSON-RPC over stdio, `ping`/`render`/`runAxe` | A | ✅ done, 15 protocol tests |
| A1.2 `crawler/render.ts` — Chromium, network-idle + mutation settle | A | ✅ done — real `MutationObserver` settle (no mutations for 500ms, capped at 10s), regression-tested against a fixture that mutates for ~1.5s then stops |
| A1.3 `RenderArtifact` capture, cache key | A | ✅ done — artifacts under `.verity/cache/<sha256>/`, key = hash(DOM + styles + screenshot), verified stable across re-renders. Element screenshots are A2.2 (next week) |
| A1.4 `static/axe.ts` — axe-core unmodified, all four arrays | A | ✅ done, all four buckets returned |
| B1.1 `schemas.py` | B | ✅ done |
| B1.2 `rpc_client.py` | B | ✅ done |
| B1.3 `main.py` single-URL pipeline | B | ✅ fixed by B (92e4f4d) — calls `runAxe` with `artifactId`, reads nested `page_state.content_hash`. Worker path and SC-attribution bugs found in review and fixed since |
| B1.4 `cli.py` | B | ✅ working — `verity scan <url>` runs end to end; exits 1 on authoritative findings, 0 on a clean page |
| B1.5 `eval/inject/` three fault injectors | B | ❌ **not started** — only a README. Plan states *"The injector must ship this week"* |
| Pair session: generate TS types from Pydantic JSON Schema | Both | ❌ not done — the TS types are hand-written and match by convention, not generation |
| ADR-0001 | Both | ⚠️ written, but not co-signed by both engineers |

**GATE MET** — `verity scan <file://.../contrast-fail.html>` emits exactly
one authoritative SC 1.4.3 finding on `#low-contrast-text` and exits 1;
the clean fixture emits none and exits 0. Remaining Week 1 items (TS type
generation, ADR co-signing, B1.5 injectors) are still open.

*Superseded — kept for history:* B1.3's wrong method name (the CLI
cannot complete a scan) and B1.5 (Week 2 cannot measure precision
without labelled data).

### Directory layout — resolved

`node-worker/` now matches the Bible: `rpc/`, `crawler/`, `static/`,
plus placeholder `interaction/` (W4) and `state_explorer/` (W17). The
earlier `src/browser/` + `src/handlers/` layout is gone.

One known deviation, already documented in
[`A1.1-explained.md`](../node-worker/A1.1-explained.md): the built
entry point is `dist/rpc/server.js`, while A1.1's acceptance criterion
is written as `node dist/server.js`. The criterion assumes a flat
layout; the Bible's own directory spec implies the nested one. A `bin`
entry (`verity-worker`) is exposed in `package.json` so callers have a
stable name either way. Nothing depends on the flat path.

---

## 5. Week 2 (17–23 Aug) — Spike A

⚠️ **The project's #1 risk.** *Can an 8B open vision model make
accessibility judgments without generating false positives?* If the
answer is no, the project continues in reduced form — but it must
continue **knowingly**.

**Monday, before any results are seen:** both engineers independently
propose a **precision bar** — the specific number below which Vision
gets descoped — then agree one number and write it down. Setting the
bar after seeing results is how a broken differentiator survives into
production. Agree the **latency bar** too.

### Engineer A (Rohan)

| # | Task | Acceptance |
|---|---|---|
| A2.1 | Element-level screenshot capture: for any selector, produce a cropped PNG plus its bounding box in CSS pixels and device pixels | Crops align with the element at both 1× and 2× device pixel ratios |
| A2.2 | Extend `RenderArtifact` with an `element_screenshots` map keyed by selector | Populated for every image and every text node axe flagged as `incomplete` |
| A2.3 | Build the Spike A corpus harness: run the three Week 1 injectors across 30 clean source pages → ~200 labelled cases | Corpus regenerable from a single command, version-controlled by manifest, **not** by committing binaries |

**A2.3 depends on B1.5 existing.** If the injectors slip further,
raise it at the Wednesday sync — this is exactly what question 1 of the
mid-week sync is for.

### Engineer B (Nikhil)

| # | Task |
|---|---|
| B2.1 | Qwen3-VL-8B-Instruct at Q4 via mlx-vlm; record cold load, tokens/sec, peak memory in `docs/measurements/spike-a.md` **on the actual target hardware** |
| B2.2 | Alt-text meaningfulness judge, rubric-based, mandatory `unknown` option |
| B2.3 | Focus-visible judgment from before/after screenshot pairs |
| B2.4 | Contrast-region localisation — **the model returns a bounding box only; it is never asked for a ratio** |
| B2.5 | End-to-end page latency: render → all three tasks → findings emitted |

**Saturday pair session (2 hrs):** review results together, make the
descope decision **jointly**. Produce **ADR-0002: Vision agent scope**
recording the measured numbers, the pre-set bar, and the decision —
whichever way it goes.

**Gate (Sun 23 Aug):** AI-assisted precision ≥ the bar written down on
Monday. Latency is a *second, independent* gate — if a single page
takes 90 seconds, "runs in CI" is quietly false and the Week 17
caching/bounding work must be pulled forward.

---

## 6. Open scrum decisions

### 6.1 The agentic remediation layer is researched but unscheduled

The Research Brief specifies a LangGraph remediation loop (Planner →
specialist Fixers on disjoint findings → advisory Critic →
**deterministic Verifier as the only gate**) with its own staged
timeline: Stage 0 model de-risking (W1–4), Stage 1 *agentless baseline*
(W4–8), Stage 2 LangGraph (W8–18), Stage 3 self-hosted evals (W12–24),
Stage 4 security hardening (W18–26).

**None of that appears in the 20-week Execution Plan**, which is
detection-only. The two documents describe different scopes on
overlapping weeks.

This matters because the remediation loop is the part of the project
that most directly serves AI-Engineer / Agentic-AI interviews. Three
options:

| Option | Cost | Consequence |
|---|---|---|
| **Detection only** (current Execution Plan) | 20 weeks as planned | Strong ML-systems + eval story; weak on "have you built an agent?" |
| **Detection + Stage 1 agentless baseline** | ~2–3 extra weeks | Gets a real fix-loop, a control group, and an honest answer to *"does multi-agent even help?"* — the Brief argues this baseline is the load-bearing artifact regardless |
| **Full LangGraph loop** | ~8+ extra weeks | Strongest agentic story; materially threatens the 10 Jan date |

**Recommendation: option 2.** The Brief's own guidance is to build the
agentless baseline *before* the agent loop and only keep the loop if it
measurably beats the baseline — so the baseline is required work in
either case, and it's the cheaper half. Decide before Week 6, since
Phase 2 is where it would slot.

### 6.2 Other open items

- [x] ~~Directory layout: rename to match the Bible~~ — done;
      `node-worker/` is now `rpc/`, `crawler/`, `static/`, with
      `interaction/` and `state_explorer/` placeheld.
- [ ] Co-sign ADR-0001 (currently unsigned).
- [ ] **W9 gate (25 Oct):** decide on the two unscheduled scope items
      in [`ownership-proposal.md`](ownership-proposal.md) — agentless
      baseline and MCP adapter — against the remaining buffer.
- [ ] Decide whether `docs/teachback/` starts retroactively at W1 or
      from W2.
