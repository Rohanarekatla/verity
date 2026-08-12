# Team Plan — Ownership, Rotation, and Role Targeting

**Owner:** Rohan (scrum lead) · **Team:** Rohan (A), Nikhil (B)
**Goal:** ship Verity *and* have both engineers able to speak to every
layer of it in an AI Engineer / Agentic AI interview.

---

## 1. Why we rotate

The original split was one lane per person: A owns the browser and
TypeScript, B owns Python, ML, and the trust machinery. That was the
right call for Week 1 — it let both sides start on day one without
blocking each other.

It's the wrong call from Week 2 onward, for two reasons:

1. **Single points of knowledge.** If only one of us can explain the
   calibration layer, that's a bus factor of one on the most
   interesting part of the project.
2. **It halves each person's interview surface.** Neither of us is
   applying for "the TypeScript half of a project" roles. We each need
   to be able to walk an interviewer through the model layer *and* the
   systems layer.

This was always the intent — the Week 1 design doc already says *"we
rotate a module at every phase boundary so neither of us becomes a
single point of knowledge."* It just never got executed. This document
executes it.

## 2. The rotation rule

> **Every phase, each engineer owns one thing in their strong lane and
> one thing in their weak lane. The strong-lane person reviews the
> weak-lane person's PR.**

Reviewing is not optional — it's the mechanism that transfers the
knowledge. A PR into a lane you don't own gets reviewed by the person
who does, and the review is where the teaching happens.

**Definition of done for a rotated module:** the person who *didn't*
write it can explain it end to end without the author present.

## 3. Rotation schedule

| Phase | Rohan (A) | Nikhil (B) |
|---|---|---|
| **P1 · W1–5**<br>De-risking | node-worker RPC, Playwright, axe-core ✅<br>**+ fault injectors** (`eval/inject/`, Python) | schemas, rpc_client, CLI ✅<br>**+ Spike A** (vision precision) |
| **P2 · W6–9**<br>Vertical slice | **SARIF + GitHub Action** (Python + CI)<br>+ MCP adapter (see §5) | **Interaction Agent** — keyboard traversal, APG contracts (browser work) |
| **P3 · W10–13**<br>Vision | **Model loader, quantisation, latency budget** (MLX infra) | **Element capture + region grounding** (browser-side) |
| **P4 · W14–17**<br>Eval | **Calibration** (isotonic, conformal) | **Caching + crawl bounding** (crosses both) |
| **P5 · W18–20**<br>Launch | Docs, ADR write-ups | Docs, ADR write-ups |

Weak-lane assignments are in **bold**. Note that by Phase 4 each of us
has touched: browser automation, protocol design, ML serving,
calibration, eval methodology, and CI.

## 4. Week 2 assignments (17–23 Aug)

Week 2 is **Spike A** — the project's #1 risk gate. Read the plan's
Week 2 section before starting.

### Blocker to clear first

Spike A gates on *"AI-assisted precision ≥ your pre-set bar."* You
cannot measure precision without labelled data, and **the fault
injectors don't exist yet** — `eval/inject/` contains only a README.
The plan itself flags this: *"The fault injector must exist this week.
You cannot gate Week 2 on precision without labelled data to measure
against."* It slipped from Week 1.

### Assignments

**Rohan — fault injectors (`eval/inject/`), Python**
- `strip_alt.py`, `detach_label.py`, `reduce_contrast.py`
- Each takes a clean fixture and applies exactly one known defect,
  reversibly.
- Each needs a **verification pass**: confirm the injection created
  the intended defect *and nothing else*. An injector that
  accidentally masks a second issue silently corrupts every downstream
  metric.
- This is a deliberate weak-lane assignment. It's Python, but it's DOM
  manipulation — you already understand the DOM better than anyone
  here from the render work. Good bridge task.
- Nikhil reviews.

**Nikhil — Spike A (vision precision)**
- Qwen3-VL-8B-Q4 via `mlx-vlm` against the injected corpus.
- Measure alt-meaningfulness precision, focus-visible precision.
- Rohan reviews.

**Both — Monday, before any code**
- Write down the **precision bar** — the actual number — before seeing
  any results. Deciding it afterward is how you talk yourself into a
  broken differentiator.
- Also agree the **latency bar**. If a page takes 90 seconds, "runs in
  CI" is quietly false and we need to know now, not in November.

### Deferred

`action/action.yml` (tagged "Week 2 · A8.1" in the old guide files) is
**deferred to Week 8**, per the roadmap. An Action wrapper needs SARIF
output to wrap, and SARIF is a Week 8 deliverable. The Week 2 tag was
stale.

## 5. Positioning for AI Engineer / Agentic AI roles

Honest assessment of where Verity stands against that target.

### What already lands well for **AI Engineer**

These are genuinely strong and most candidates don't have them:

- **An eval harness with fault injection and prevalence weighting.**
  Most people applying to AI eng roles have never built an eval set.
  This is the single most differentiating thing in the plan.
- **Calibration** — isotonic regression, conformal prediction, the
  understanding that raw model scores aren't probabilities.
- **Constrained decoding + mandatory escape values**, and a schema
  linter that rejects any closed-vocab field lacking an escape. This
  shows you've thought about the fabrication trap.
- **LLM-as-judge with a written rubric** (alt-text judgment).
- **Trust partitioning / provenance** — the model localises,
  deterministic math decides. This is a real design insight and it's
  the thing to lead with.

**The interview framing to use:** *"I built an ML system where the hard
problem was knowing when not to trust the model."* That's a senior
framing, and the calibration + provenance + eval work backs it up.

### What's missing for **Agentic AI**

Currently the things in `verity/agents/` are **pipeline stages, not
agents**. They run in a fixed order and don't decide anything. There's
no plan→act→observe→replan loop, no tool selection, no bounded
autonomy. An interviewer targeting agentic roles will notice.

Three additions close that gap, in order of value per hour spent:

#### (a) Expose the worker as an MCP server — highest leverage

`node-worker` already speaks **JSON-RPC 2.0 over stdio with
newline-delimited framing**. That is *literally the MCP stdio
transport*. ADR 0001 even cites MCP as the reason for choosing this
shape. We are one thin adapter away from an actual MCP server.

What it takes: the `initialize` handshake, `tools/list`, and
`tools/call` mapping onto our existing `render` / `runAxe`. Days, not
weeks.

What it buys: any MCP client (Claude Desktop, Cursor, an agent you
write) can use Verity as a tool. That turns "accessibility linter"
into "a tool an AI agent uses to audit pages" — which is exactly the
Agentic AI story, and it's real, not a demo.

**Suggested slot: Phase 2, Rohan.** It's browser/protocol adjacent, so
it's fast for A, and it's the highest-signal single addition available.

#### (b) Make the State Explorer an actual agent loop

Week 17 already plans a "State Explorer for bounded modals/menus."
Currently framed as deterministic traversal. Reframe it as a real
agent loop: *observe page state → decide which interaction to try
next → act → observe → repeat, under a hard budget.*

That's genuine agentic behaviour (planning, tool use, bounded
autonomy, termination guarantees) and it's **already on the roadmap** —
it just needs framing and a decision policy instead of a fixed
traversal order. Nearly free.

#### (c) Give the validator tool access

The adjudication step (dedup, provenance stamping, severity) could
call back into the browser to gather more evidence before deciding —
e.g. re-screenshot a region, query the AX tree again. That's tool use
in service of a decision, which is the core agentic pattern.

Lower priority than (a) and (b).

### What we should *not* do

Do not pivot the project into a chatbot or a RAG demo to look more
"AI." Verity's differentiator is that it's a **trust-partitioned ML
system with a real eval story**. That is rarer and more interesting
than another RAG app. Add the agentic surface on top; don't trade away
the foundation.

## 6. Working agreements

- **Rotation PRs get reviewed by the lane owner.** Non-negotiable —
  the review is the knowledge transfer.
- **Sunday gate, 30 minutes, both of us.** Did the gate pass? If not,
  is it a one-week slip or a design problem? What comes off the list
  to protect next week?
- **Slip rule:** if a gate slips two weeks, cut scope. Hold the date.
  Never cut the eval harness.
- **Contract changes** (`protocol.ts` ↔ `schemas.py`) need both sides
  updated in the same PR. See [CONTRIBUTING.md](../CONTRIBUTING.md).
- **ADRs for non-obvious decisions**, written when the decision is
  made. These become interview material later — that's a real reason
  to write them, not a bureaucratic one.

## 7. Open items

- [ ] Confirm the ABC trek dates (blocks Week 6 onward planning —
      decide before Week 3 so we know whether to compress or accept
      the shift).
- [ ] Fix `verity/orchestrator/main.py`: calls a nonexistent
      `"analyze"` method instead of `"runAxe"`, and reads
      `content_hash` flat instead of nested under `page_state`. See
      [verity/orchestrator/README.md](../verity/orchestrator/README.md).
      **Owner: Nikhil.**
- [ ] Agree the precision bar and latency bar (Monday W2, in writing,
      before results).
- [ ] Decide whether MCP adapter lands in Phase 2 or Phase 3.
