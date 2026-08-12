# Ownership Proposal — Rotate Along Feature Verticals

> **Status: PROPOSAL. Not agreed. Requires Nikhil's explicit sign-off
> before any of it takes effect.**
>
> This changes what each engineer owns. One person cannot adopt it
> unilaterally — that is the whole point of writing it down as a
> proposal rather than editing [`team-plan.md`](team-plan.md) directly.

## The problem this solves

The Execution Plan's rotation (§1.4) transfers one module per phase
boundary. It is well-designed for its stated goal — eliminating single
points of knowledge — and it works.

It does not, however, distribute *kinds* of work evenly. Sorted by what
an AI-Engineer interview actually probes, the high-signal modules are:

| Module | Why it signals | Currently |
|---|---|---|
| Eval harness — fault injection, prevalence weighting, per-SC precision/recall | *"Red flag if the candidate doesn't start with evals"* is a verbatim take-home rubric line | Track B |
| Confidence calibration — isotonic, conformal prediction | Rare. Most candidates have never fit a calibration curve | Track B (→A at W9) |
| Constrained decoding + escape values + the fabrication trap | Directly probed; shows model-failure judgment | Track B |
| Agentless baseline + "does multi-agent help?" | The single most defensible agent answer available | **Unowned** |
| Prompt-injection hardening | OWASP #1 for LLM apps; Verity ingests hostile pages | **Unowned** |

Under the current table, Engineer A receives exactly one of these
(calibration, at the end of Week 9) and gives away browser modules to
get it. Engineer A finishes the project having built the systems half
of an ML system.

**The fix is not a faster rotation.** Cycling the same table every two
weeks just pays the receiving-engineer slowdown twice as often while
still routing the ML work to one person.

## The principle: rotate along feature verticals, not language borders

The current table splits by *component*, which usually means by
language. Splitting by **feature vertical** — one engineer owns a
capability end to end, across both languages — gets cross-language
exposure at a fraction of the context-switching cost, because the
receiving engineer already holds half the context.

**Worked example — Week 3, contrast-over-image.** The plan already
assigns A the pixel-sampling half (canvas sampling, `devicePixelRatio`,
glyph-region estimation) and B the Python adjudicator
(`verity/agents/contrast.py`). Those are two halves of *one* feature.
Giving the whole vertical to A means:

- A writes Python in **Week 3 (31 Aug)** rather than Week 9 (25 Oct) —
  **eight weeks earlier**.
- The onboarding cost is near zero, because A already owns the pixel
  data the adjudicator consumes.
- A owns the project's flagship principle — *the model localises, the
  math decides* — end to end, which is the strongest single thing to
  talk about in an interview.

That is the pattern applied below.

## Proposed ownership

Primary owner listed first. **Bold** = the engineer's weak lane, which
is the point. "Pair" = built jointly at one screen, both can claim it.

### Phase 1 · W1–5

| Wk | Work | Owner |
|---|---|---|
| 1 | Polyglot skeleton, render, axe | A (done) / B (done) |
| 2 | Spike A — vision precision | B · A owns corpus harness (A2.3) |
| 3 | **Contrast-over-image, full vertical** — TS pixel sampling *and* `agents/contrast.py` | **A** |
| 4 | Keyboard traversal + trap detection | A |
| 5 | Consolidation, ADRs, no new risk | Both |

### Phase 2 · W6–9

| Wk | Work | Owner |
|---|---|---|
| 6 | Finding/provenance model, TS mirror generation | B · A reviews |
| 7 | Dedup + waiver-as-code | B |
| 8 | **SARIF + GitHub Action** — Python output, CI surface | **A** |
| 9 | Interaction Agent + 5 APG contracts | A |

**Boundary W5:** A → B, Static/DOM Agent *(unchanged from plan)*

### Phase 3 · W10–13

| Wk | Work | Owner |
|---|---|---|
| 10 | Florence-2 grounding, OCR, model loader | B · A pairs |
| 11 | **Alt-text judge, constrained decoding, escape values** | **A** |
| 12 | **Confidence calibration** — isotonic + conformal | **A** |
| 13 | Observability, graceful degradation | A |

**Boundary W9:** B → A, calibration *(unchanged)* · A → B, SARIF/Action

### Phase 4 · W14–17

| Wk | Work | Owner |
|---|---|---|
| 14 | Full fault-injection harness, prevalence weighting | **Pair** |
| 15 | ACT test-case runner, EARL report | B |
| 16 | VPAT / ACR generator | B |
| 17 | Caching, crawl bounding, State Explorer | A |

**Boundary W13:** A → B, Interaction Agent *(unchanged)*

### Phase 5 · W18–20

| Wk | Work | Owner |
|---|---|---|
| 18 | Performance, Linux/CUDA path | Both |
| 19 | Documentation, license ledger | Both |
| 20 | Launch, ACT submission, retrospective | Both |

**Boundary W17:** B → A, report generation *(unchanged)*

### What each engineer ends with

**A:** browser/Playwright, JSON-RPC transport, contrast vertical
(TS+Python), keyboard/APG, SARIF+CI, constrained decoding + fabrication
handling, calibration, observability, caching/state — plus co-ownership
of the eval harness.

**B:** Pydantic modelling and cross-language schema generation, dedup
and waiver machinery, vision grounding + OCR + model serving, ACT
conformance, VPAT/ACR, Static/DOM agent, Interaction Agent — plus
co-ownership of the eval harness.

Both retain real ML. Neither is reduced to a support role. **This only
holds if Nikhil agrees it's fair** — see the risk section.

## Start immediately, at zero delivery cost

Three rituals from the Execution Plan are specified and **not running**.
They give continuous cross-lane exposure without touching the schedule,
and they start Monday:

1. **Monday shared block** — 60 minutes, *identical material*, both
   engineers. This is the single biggest lever and it costs nothing.
2. **Explain-to-approve review** — approving Nikhil's Python means
   writing three lines describing its mechanism in your own words. You
   cannot do that without reading it properly. Continuous Python
   exposure, disguised as review.
3. **Sunday teach-back** — you write the notes on *his* work, into
   `docs/teachback/YYYY-WW.md`. Notes you can't write are the gap list
   for next week.

Do these for four weeks and the W9 calibration handover stops being a
cliff.

## Scope additions worth making

Both are currently unowned. Both serve the resume goal directly.

**1 · Agentless baseline (~2 weeks, slot in Phase 2 or 3) — A**
A one-shot localise → propose-diff → apply-in-sandbox → re-check
pipeline, no Planner, no Critic. The Research Brief's guidance is to
build this *before* any agent loop and only keep the loop if it
measurably beats the baseline. It is therefore required work under
either decision, and it is the cheaper half. It yields the honest,
defensible interview answer: *"multi-agent rarely wins on tightly-
coupled tasks — I benchmarked mine against an agentless baseline."*

**2 · MCP server adapter (~2–3 days) — A**
`node-worker` already speaks JSON-RPC 2.0 over newline-framed stdio,
which *is* the MCP stdio transport; ADR-0001 cites MCP as the reason
for that choice. Adding `initialize`, `tools/list`, and `tools/call`
over the existing `render`/`runAxe` makes Verity usable as a tool by
any MCP client. Highest signal-per-hour available on this project.

**Where the weeks come from:** Weeks 18–19 are the *only* genuine
buffer in the plan. Spending them on scope means any earlier slip has
nowhere to go. Do not adopt both additions unless Phases 1–3 land on
time. Decide at the W9 gate, with three phases of evidence, not now.

## Risks — read before adopting

**1 · This reassigns Nikhil's work, and he has career goals too.**
He chose Track B. This proposal moves calibration, constrained
decoding, and the contrast adjudicator toward A. If he wanted those,
this is a demotion dressed as a rotation, and it will damage the
working relationship far faster than any schedule slip.

*Mitigation:* take it to him as a question, not a decision. The honest
version is co-ownership — both engineers pair on the AI-critical
modules so both can legitimately claim them. The knowledge-parity
protocol exists to make everyone able to explain everything, **not** to
route the interesting modules to one person.

**2 · Rotation has a real cost, and this adds rotations.**
The Execution Plan states the receiving engineer is slowed roughly a
week per transfer. Feature-vertical ownership reduces but does not
eliminate that.

**3 · Scope additions threaten the 10 Jan date.**
The plan's own slip rule: *when a gate fails twice, cut scope, never
extend the timeline.* Adding the agentless baseline and MCP is ~2.5
weeks against a 2-week buffer. That is why the decision is deferred to
the W9 gate.

**4 · The thing that would actually hurt the resume is not shipping.**
A finished, honest, well-evaluated detection engine beats a
half-finished one with an agent loop bolted on. The Research Brief
already rates this project *"an unusually strong portfolio piece"* on
its current scope — trust-partitioning, deterministic verifier over
LLM-judge, CI-native evals, local-model constraints. Protect that
before adding to it.

## Decision needed

- [ ] Nikhil reviews this and says yes, no, or counter-proposes
- [ ] If yes: fold into [`team-plan.md`](team-plan.md) §2.4, delete this file
- [ ] If no: keep the Execution Plan's table; turn the three rituals on regardless
- [ ] Either way: rituals start Monday — they need no agreement to be useful
