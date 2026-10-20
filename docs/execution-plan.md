# Execution Plan — All 20 Weeks

> **2026-10-20:** Phases 3–5 are revised — *PLAN v2 — Phases 3–5 revised:
> agent accessibility* is the plan in force (ADR-0005, accepted). The original
> Phases 3–5 are kept below for history.


Condensed, greppable transcription of *Verity — Execution Plan*
(10 Aug 2026 → 10 Jan 2027). The source PDF is authoritative and has
fuller reasoning; this exists so the schedule is in the repo, next to
the code, and searchable.

**Rituals, week shape, and the knowledge-parity protocol:**
[`team-plan.md`](team-plan.md).

Legend: **A** = Engineer A (Rohan) · **B** = Engineer B (Nikhil) ·
**S** = shared · ▶ = gate · ⚠ = risk gate

---

# PHASE 1 — FOUNDATIONS & DE-RISKING · W1–5 · 10 Aug – 20 Sep

*Answer the question that can kill the project before building on top
of the answer, and ship a working vertical slice regardless.*

## Week 1 · 10–16 Aug — Polyglot skeleton, first authoritative finding

**Learning:** WCAG 2.2 structure; 86-vs-87 and why 4.1.1 is obsolete;
axe's four result arrays and why `incomplete` exists; the CDP AX tree
and why it ≠ what a screen reader announces.
**Artifact (both):** one-page note — *"The four axe buckets and what
each means for provenance."*

| # | A |
|---|---|
| A1.1 | `rpc/server.ts` — line-delimited JSON-RPC 2.0 over stdio: `ping`, `render`, `runAxe` |
| A1.2 | `crawler/render.ts` — Chromium, network-idle **plus** DOM-mutation settle (no mutations 500 ms, capped 10 s) |
| A1.3 | `RenderArtifact` capture → `.verity/cache/<sha256>/`; stable key from DOM + styles + screenshot |
| A1.4 | `static/axe.ts` — axe-core as an unmodified dependency, all four arrays verbatim |

| # | B |
|---|---|
| B1.1 | `models/schemas.py` — full Pydantic set; `Provenance` required on `Finding`, no default |
| B1.2 | `orchestrator/rpc_client.py` — long-lived asyncio subprocess, correlate by id, per-call timeout |
| B1.3 | `orchestrator/main.py` — render → runAxe → `Finding` with `provenance=AUTHORITATIVE` |
| B1.4 | `cli.py` — `verity scan <url>`, non-zero exit on authoritative findings |
| B1.5 | `eval/inject/` — `strip_alt`, `detach_label`, `reduce_contrast`, reversible, each unit-tested |

**Pair (Sat, 90 min):** generate the TypeScript types from the Pydantic
JSON Schema and wire the boundary. **ADR-0001.**
▶ **Gate Sun 16 Aug —** a real production page produces a correct
authoritative contrast finding **through the CLI**.

> **The injector must ship this week.** Week 2's gate is a precision
> measurement, and a precision measurement without labelled data is not
> a measurement.

## Week 2 · 17–23 Aug — ⚠ SPIKE A, vision model precision

*Can an 8B open vision model make accessibility judgments without
generating false positives?* If no, the project continues in reduced
form — but **knowingly**.

**Learning:** GUI-grounding benchmarks read sceptically; Instruct beats
Thinking on grounding; **the fabrication trap** — constrained decoding
produces well-formatted dishonesty when a required field has no
supporting evidence; why FP is the headline metric and recall secondary.
**Artifact (both, before any results):** the **precision bar** — the
number below which Vision is descoped. Propose independently, agree
one, write it down Monday.

| # | A | | # | B |
|---|---|---|---|---|
| A2.1 | Element-level screenshot capture: cropped PNG + bbox in CSS and device px | | B2.1 | Qwen3-VL-8B-Instruct Q4 via mlx-vlm; cold load, tokens/sec, peak memory → `docs/measurements/spike-a.md` on **target hardware** |
| A2.2 | `element_screenshots` map on `RenderArtifact`, keyed by selector | | B2.2 | Alt-text meaningfulness judge, rubric, mandatory `unknown` |
| A2.3 | Spike A corpus harness — 3 injectors × 30 clean pages ≈ 200 labelled cases, regenerable by one command, manifest-versioned | | B2.3 | Focus-visible judgment from before/after pairs |
| | | | B2.4 | Contrast-region localisation — **bounding box only, never a ratio** |
| | | | B2.5 | End-to-end page latency |

**Pair (Sat, 2 hrs):** descope decision made **jointly**. **ADR-0002.**
▶ **Gate Sun 23 Aug —** AI-assisted precision ≥ Monday's bar. **Latency
is a second, independent gate:** if a page takes 90 s, "runs in CI" is
quietly false and Week 17's caching work must be pulled forward.

## ⏸ 24–30 Aug — no work scheduled
If the gate failed, this is for re-planning, not rest. Rewrite Phases
3–5 around the fallback before Week 3.

## Week 3 · 31 Aug – 6 Sep — Contrast-over-image adjudication

*The first wedge: resolving findings axe explicitly declines to judge,
while keeping the result authoritative.*

**Learning:** WCAG 2.x contrast math in full; thresholds; known
limitations; why APCA is advisory only; **the governing principle —
the model localises, the math decides.**
**Artifact (both):** implement relative luminance by hand from the spec
text before importing any library. The two implementations must agree
to six decimal places.

| # | A | | # | B |
|---|---|---|---|---|
| A3.1 | Pixel sampling from a text bbox at correct device-pixel scale | | B3.1 | `agents/contrast.py` — worst-case ratio from fg colour + background samples |
| A3.2 | Glyph-region estimation — text pixels vs background pixels | | B3.2 | Adjudication pipeline over axe `incomplete` → `provenance=AUTHORITATIVE`. **No model in this path** |
| A3.3 | Per-region background sample set, not a single average | | B3.3 | Inconclusive (animation, video, cross-origin canvas) → `outcome=cantTell`, `NEEDS_REVIEW` |
| A3.4 | `sampleRegion(selector)` on the RPC surface | | B3.4 | `contrast_over_image` injector |

**Pair (90 min):** walk axe-`incomplete` → authoritative together.
**ADR-0003: the model localises, the math decides.**
▶ **Gate Sun 6 Sep —** beats axe-core recall on contrast-over-image
fixtures at **zero new false positives**.

## Week 4 · 7–13 Sep — Keyboard traversal and trap detection

*The second wedge, and the higher-value one — automated tools detect
keyboard issues at ~2.49%.*

**Learning:** APG as machine-checkable specs; accname computation; why
real screen readers are excluded from CI (it converts the highest-risk
dependency into a pure function).
**Artifact (both):** the tablist APG contract as YAML, by hand, before
any runner code.

| # | A | | # | B |
|---|---|---|---|---|
| A4.1 | Tab-order capture with selectors + bboxes; shadow DOM and iframes handled or reported unvisited | | B4.1 | Map interaction results to SC 2.1.1 / 2.1.2 / 2.4.3 / 2.4.7 |
| A4.2 | **Multi-cycle trap detection** — assert only after N full cycles; **determine N by measurement**, record in `docs/measurements/` | | B4.2 | Three-state outcome: `pass`/`fail`/`indeterminate`; indeterminate → `NEEDS_REVIEW` |
| A4.3 | Focus-visible: before/after screenshot diff + indicator contrast | | B4.3 | Injectors: `keyboard_trap`, `positive_tabindex`, `outline_none` |
| A4.4 | `rulepacks/apg-contracts/` schema + loader | | B4.4 | Retry policy — re-run indeterminate to a fixed cap |

**Pair (2 hrs):** run against APG reference implementations. **Every
false alarm on a correctly-built widget is a design bug and must be
fixed this week.** **ADR-0004.**
▶ **Gate Sun 13 Sep —** injected trap detected; **zero false alarms**
on clean APG widgets.

## Week 5 · 14–20 Sep — Consolidation (planned light week)

No new technical risk. Shared block only (45 min): ACT Rules Format,
read-only.

| # | S |
|---|---|
| S5.1 | ADRs 0001–0004 written into `docs/adr/`, **both sign each** |
| S5.2 | README skeleton in the prescribed order |
| S5.3 | Test-coverage pass on Phase 1; CI green from a clean checkout |
| S5.4 | **Bus-factor test #1** — A breaks a Track B component, B diagnoses unaided in 30 min. Then reverse |
| S5.5 | **Rotation #1: Static/DOM Agent A → B.** Handover note in `docs/handover/`; B pushes one non-trivial commit to it |

▶ **Gate Sun 20 Sep —** Phase 1 demoable end-to-end from a clean
checkout, all Phase 1 ADRs written, both pass the bus-factor test.

## ⏸ 21–27 Sep — no work scheduled
Before leaving: push everything, commit a *state-of-play* note to
`docs/status.md`. Neither engineer will reliably recall this in October.

---

# PHASE 2 — VERTICAL SLICE · W6–9 · 28 Sep – 25 Oct

*Turn a prototype into a tool a stranger could install and run in CI.
The trust machinery is built here, because it is what distinguishes a
product from a script.*

## Week 6 · 28 Sep – 4 Oct — Finding model, provenance, dedup

**Learning:** provenance as a *type-system* concern, not a reporting
one — a default is a silent decision; dedup by (SC, normalised
selector, region) with **strongest provenance wins**.
**Artifact (both):** write the dedup rule as pseudocode independently,
including tie-breaking, then reconcile.

| # | A | | # | B |
|---|---|---|---|---|
| A6.1 | Selector normalisation — stable across generated class-name churn | | B6.1 | `agents/validator/dedup.py` |
| A6.2 | Region identification for findings without a clean selector | | B6.2 | Provenance stamping **enforced at construction time** |
| A6.3 | Regenerate the TS mirror from JSON Schema + **CI check that fails on drift** | | B6.3 | Severity assignment |
| | | | B6.4 | Validator as a versioned, independently testable module (no browser) |

**Pair (90 min):** **ADR-0005: provenance is a required enum** —
including why a default would be actively harmful.
▶ **Gate Sun 4 Oct —** no path through the codebase produces a finding
without an explicit provenance value.

## Week 7 · 5–11 Oct — Waivers and baseline diffing

*Without these, the first team to install Verity sees hundreds of
pre-existing failures and uninstalls it.*

**Artifact (both):** design the waiver signature **adversarially** —
each engineer tries to construct a benign DOM change that breaks the
other's scheme.

| # | A | | # | B |
|---|---|---|---|---|
| A7.1 | Stable `finding_signature` — survives a formatter and a class-name hasher | | B7.1 | `waivers.yaml` schema: signature, justification, approver, expires, created — all required |
| A7.2 | Baseline storage — content-addressed, human-readable diff | | B7.2 | Suppression: `waived=true`, excluded from gating, retained in report |
| | | | B7.3 | **Expiry enforcement** — expired waiver fails CI, naming the waiver |
| | | | B7.4 | Diff/regression keyed to `ruleset_version` + corpus hash |

**Pair:** **ADR-0006** (waiver signature), **ADR-0007** (baseline-first
gating).
▶ **Gate Sun 11 Oct —** on a page with 50 pre-existing findings,
introducing one new defect fails the build on **exactly that one**.

## Week 8 · 12–18 Oct — SARIF + GitHub Action · *the first useful thing*

At the end of this week Verity is installable and does something no
free tool does well. **Consider a soft public release.**

**Artifact (both):** hand-write a minimal valid SARIF file and confirm
it renders as inline annotations **before** writing generator code.
Catches spec misreadings in twenty minutes instead of two days.

| # | A | | # | B |
|---|---|---|---|---|
| A8.1 | `action/` — GitHub Action wrapping the CLI | | B8.1 | `report/sarif.py` — authoritative→error, AI-assisted→warning, needs-review→note |
| A8.2 | Action caches model + browser binaries between runs | | B8.2 | `partialFingerprints` from the stable signature |
| A8.3 | Baseline-commit workflow — proposes a baseline update as part of a PR, never automatic | | B8.3 | JUnit output |
| | | | B8.4 | Gating policy via `ci: { fail_on, annotate_on }`; default `fail_on: authoritative` |

**Pair (2 hrs):** end-to-end on a real demo repo, both watching a PR
annotation appear. **This is the surface a stranger judges the project
by.**
▶ **Gate Sun 18 Oct —** PR annotations appear inline; build fails only
on **new authoritative** findings.

## Week 9 · 19–25 Oct — Interaction Agent + first five APG contracts

**Artifact (both):** each writes contracts for two of the five
patterns independently; the fifth together. Cross-check all five.

| # | A | | # | B |
|---|---|---|---|---|
| A9.1 | Contract runner — identify by ARIA role, load contract, drive keys, capture transitions | | B9.1 | Announcement prediction via `computeAccessibleName` + role/state |
| A9.2 | Widget inventory from Static, consumed by Interaction — never speculative | | B9.2 | Virtual screen reader in CI (headless Linux, no real SR anywhere) |
| A9.3 | Loop guard + per-widget interaction budget | | B9.3 | Shadow-DOM accname supplement |
| A9.4 | **Contract-fixture CI gate** — every contract ships a passing *and* a failing fixture; harness rejects contracts that don't fail their fail-fixture | | B9.4 | ARIA-misuse injectors |

**Pair (2 hrs):** **Bus-factor test #2**, then **Rotation #2:
confidence & calibration B → A, ahead of Phase 3.**
▶ **Gate Sun 25 Oct —** all five APG reference implementations pass;
all injected misuse fails; zero false alarms.

---

# PLAN v2 — PHASES 3–5 REVISED: AGENT ACCESSIBILITY · W10–20 · 26 Oct – 10 Jan

> **Status: IN FORCE (ADR-0005 accepted 2026-10-20).** It supersedes the
> original Phases 3–5 kept below for history. Research behind every choice:
> `docs/research/agent-accessibility-2026.md`.

**The thesis.** Accessibility for people and for AI agents is the same
engineering problem — both read the web through the accessibility tree — and
Verity is the only tool that measures both, with verdicts a deterministic
check stands behind. **The model proposes, the maths decides** applies to
agents exactly as it did to vision.

**What ships on 10 Jan (four deliverables, priority order):**

| # | Deliverable | One line |
|---|---|---|
| D1 | **Agent Accessibility Benchmark** | First controlled, pre-registered study of how WCAG defects change web-agent task success — per defect type, agent type, model |
| D2 | **`verity agent-check`** | One command: an LLM agent attempts your site's task through the a11y tree + keyboard; every failure pinned to a step and *confirmed* by Verity, or marked needs-review |
| D3 | **Verifier-gated remediation** | Verity as an MCP server; a fix loop that accepts a patch only when Verity proves the defect gone and no regression; WebMCP checks + declarations |
| D4 | **Agent Readiness Report** | Deterministic agent-readiness scan of a large public site list + real agent tasks on a sample — the launch headline |

## Operating rules for v2 (why this plan works)

1. **Always shippable.** Every milestone leaves a releasable product: M1 (W12)
   benchmark v1 results are a publishable blog post on their own; M2 (W14) is
   agent-check; M3 (W16) remediation. A slip removes the *last* milestone, never
   breaks an earlier one.
2. **Pre-registration before measurement.** Hypotheses, metrics, sample sizes
   and analysis are committed (W11) before any benchmark run. A null result is
   publishable; a fished result is not.
3. **Budget is a gate, not a hope.** The runner enforces a hard spend cap; the
   W10 pilot measures tokens/episode before any run is sized.
4. **Pinned environments.** Every app under test is a vendored, pinned commit
   in Docker. Upstream churn cannot break a result.
5. **The cut order is fixed now** (end of this section), so nobody negotiates
   scope at 1 a.m. in Week 17.
6. **Kill criteria keep their teeth** (ADR-0005), and the deterministic product
   ships regardless — exactly as ADR-0002 guaranteed for vision.

## Architecture additions

```
                ┌──────────────── Python ────────────────┐
 tasks + truth  │ eval/agentbench/                        │
 (YAML) ───────▶│   runner ── budget cap, seeds, resume   │
                │   agents/ ── tree_agent (ours, AXTree)  │──▶ results/*.parquet ──▶ analysis (CIs, paired tests)
                │           ── browser_use (DOM+vision)   │
                │           ── sr_agent (virtual SR, B9.2)│
                │   providers/ ── Anthropic · OpenAI ·    │
                │                 Ollama (local)          │
                └──────┬──────────────────────────────────┘
                       │ Playwright (BrowserGym-compatible obs/actions)
                ┌──────▼──────────────────────────────────┐
                │ environments: MiniWoB++ (BrowserGym)    │
                │   · vendored apps in Docker (pinned)    │
                │   · WebArena shopping/forum (fallback)  │
                │ defect injection at page load           │──▶ injection verified by Verity (A14.2)
                │   (init scripts reusing eval/inject)    │
                └─────────────────────────────────────────┘
 verity agent-check ── same agent + Verity's deterministic checks on the failing step
 verity mcp          ── scan · sample contrast · traverse · contracts · virtual SR · baseline diff
```

Defects are injected **at page load** (Playwright init scripts built from the
existing `eval/inject` injectors), so the apps' source never changes, every
variant is reproducible from (app commit, injector, seed), and Verity verifies
that exactly the intended defect — and no other — is present (pulled forward
from A14.2).

## Week 10 · 26 Oct – 1 Nov — Pilot, harness skeleton, model providers

**Learning:** BrowserGym's observation/action spaces; why tree-only agents are
the right primary subject (it is the interface Playwright MCP and Atlas use);
tokens-per-episode economics; prompt caching.
**Artifact (both):** **the pilot** — one tree-only agent, one local and one
frontier model, 5 MiniWoB++ tasks × {clean, label stripped, div-button}, 10
trials each. Its only job is to measure cost and variance so W12 can be sized.

| # | A | | # | B |
|---|---|---|---|---|
| A10.1–3 | ✅ Done 19 Oct (image inventory, store-once crops, OCR triage) | | B10.1–2 | OCR / grounding → **optional**, behind the ADR-0002 flag |
| A10.4 | `eval/agentbench/agents/tree_agent.py` — AXTree-only observation, BrowserGym action set, step cap, full trace | | B10.3′ | **Provider layer** (was "model loader"): Anthropic, OpenAI, Ollama behind one interface; token + cost accounting per call; prompt caching |
| A10.5 | Runtime injection: `eval/inject` → Playwright init scripts | | B10.4 | Model-load vs inference timing (kept; now per provider) |

▶ **Gate Sun 1 Nov —** pilot ran; tokens/episode, cost/episode and
per-cell variance recorded in `docs/measurements/agentbench-pilot.md`.
**Failure:** no budget is committed to W12 until it passes.

## Week 11 · 2–8 Nov — Benchmark design and pre-registration

**Learning:** experimental design for nondeterministic agents — paired
designs, McNemar's test, Wilson intervals, power; prevalence weighting
(WebAIM Million 2026: low contrast 83.9%, missing alt 53.1%, missing labels 51%,
empty links 46.3%, empty buttons 30.6%).
**Artifact (both):** **`docs/agentbench/preregistration.md`** — hypotheses,
primary metric (task success, paired clean vs defect), secondary metrics
(steps, tokens, cost), sample sizes from the pilot's variance, exclusion rules,
analysis code — committed and tagged **before any W12 run**.

Hypotheses to pre-register:
- **H1** Name defects (missing label / empty button / div-as-button) reduce
  tree-only agent success.
- **H2** Vision-capable agents are less affected than tree-only agents.
- **H3** Keyboard traps and focus defects hurt the screen-reader agent most.
- **H4** Accessible pages cost fewer tokens per successful task.

| # | A | | # | B |
|---|---|---|---|---|
| A11.1′ | Task suite: 20–30 tasks across **2–3 vendored apps** (pinned Docker; candidates: a RealWorld/Conduit frontend, an e-commerce demo, an admin/forms app) + MiniWoB++ families | | B11.1′ | **Deterministic success evaluators** per task (app state / DB / URL checks — no LLM judging success) |
| A11.2′ | **Injection verification** (pulled from A14.2): Verity asserts exactly the intended defect, nothing else; failure aborts the variant | | B11.2′ | **Schema linter + escapes** (kept from A11.1/B11.2) — applied to every agent and checker output: closed vocabularies carry `unknown` |
| A11.3 | Deterministic alt heuristics + decorative detection (kept, A11.2–A11.3) | | B11.3′ | Pre-registration document + analysis notebook |

**Pair:** sign the pre-registration; tag the commit.
▶ **Gate Sun 8 Nov —** every (task × defect) cell has a verified injection and
a deterministic evaluator; pre-registration tagged. **Failure:** no
measurement run starts.

## Week 12 · 9–15 Nov — Benchmark runs v1 (milestone M1)

**Learning:** experiment runners at scale — idempotency, resumability,
seeding, caching, cost caps; why you never look at results mid-run.
**Artifact (both):** `docs/agentbench/results-v1.md` — every pre-registered
analysis, including the ones that came out null.

| # | A | | # | B |
|---|---|---|---|---|
| A12.1′ | Runner: parallel episodes, resumable, per-episode trace, **hard budget cap** | | B12.1′ | Runs: tree agent × {2 local, 1 frontier} models × full suite × N trials |
| A12.2′ | Results store (Parquet) + dashboards (success by defect × agent × model) | | B12.2′ | Statistics: paired tests, intervals, effect sizes; per-defect-type tables |
| A12.3′ | Trace viewer: replay an episode step by step with the AXTree the agent saw | | B12.3′ | Cost model: $/successful task, tokens/step, clean vs defect |

▶ **Gate Sun 15 Nov — M1:** results v1 with intervals published internally;
blog post drafted. **Kill criterion:** clean-page success < 30% for the best
model → switch the primary suite to MiniWoB++ + simplest app tasks (effect
unmeasurable at the floor).

## Week 13 · 16–22 Nov — More agents, agent security, observability

**Learning:** indirect prompt injection against web agents (WASP: hijack rates
up to 86%); plan-then-execute and untrusted-content defences; why a tool that
quietly checks less than it claims is worse than none (kept from W13).
**Artifact (both):** `docs/degradation.md` (kept) — now including every way an
agent run can partially fail and what the report must say.

| # | A | | # | B |
|---|---|---|---|---|
| A13.1′ | **browser-use** agent (DOM + vision) wired into the runner | | B13.1′ | **Screen-reader agent** on the virtual SR (B9.2) — perceives only announcements, acts only by keyboard |
| A13.2′ | Injection-attack pages (WASP-style) as a benchmark track; hijack rate per agent | | B13.2′ | Hardening of *our* agents: plan-then-execute, page text tagged untrusted, tool allow-list; measured against A13.2′ |
| A13.3 | State labelling + loop guard (kept, A13.2–A13.3) | | B13.3 | `verity-trace.json` + graceful degradation (kept, B13.1–B13.4) |

**Pair:** Bus-factor #3; Rotation #3 (agents A → B, evaluators B → A).
▶ **Gate Sun 22 Nov —** three agent types × clean/defect measured; our agents'
hijack rate measured and reduced; kill the model backend mid-run → the run
completes and says exactly what was not checked.

## Week 14 · 23–29 Nov — `verity agent-check` (milestone M2)

**Learning:** failure localisation — from "the agent gave up" to "step 7, the
Submit control has no accessible name (4.1.2)"; why an unconfirmed agent
failure must never be reported as a site defect.
**Artifact (both):** hand-localise five real agent failures before writing the
localiser.

| # | A | | # | B |
|---|---|---|---|---|
| A14.1′ | CLI: `verity agent-check URL --task "…" [--success "…"]`, any provider incl. local | | B14.1′ | **Confirmation**: run Verity's deterministic checks (names, contracts, traversal, contrast) on the failing step's target → *confirmed* or *needs-review* |
| A14.2′ | Report: SARIF (inline PR annotations), JSON, HTML trace; GitHub Action input | | B14.2′ | **Agent-readiness score**: static (tree well-formed, names, stability, WebMCP) + dynamic (task success) — evidence for every point |
| A14.3 | Complete injector set (~15 types) + prevalence weighting (kept, A14.1/A14.3) | | B14.3 | `eval/` per-SC precision/recall harness + baseline freeze (kept, B14.1–B14.4) |

▶ **Gate Sun 29 Nov — M2:** on the injected corpus, agent-check localises the
injected defect in ≥ 80% of agent failures with **zero** wrong confirmations.
**Failure:** confirmations are disabled (everything needs-review) until zero.

## Week 15 · 30 Nov – 6 Dec — MCP server and verifier-gated fixes

**Learning:** tool design for coding agents (schemas, small outputs, idempotent
calls); verifier-gated generation; why fix rate without regression rate is a
vanity metric.
**Artifact (both):** one fix done by hand through the MCP tools, end to end,
before the loop is automated.

| # | A | | # | B |
|---|---|---|---|---|
| A15.1′ | **Verity MCP server**: scan, explain finding, sample contrast, traverse, run contract, virtual-SR read, baseline diff | | B15.1′ | **Fix loop**: finding → locate source → minimal patch in a sandbox → rebuild → re-scan → accept only if resolved **and** baseline shows no new finding; else retry ≤ 3, then hand off with reasons |
| A15.2′ | Source mapping: selector → file (source maps, React dev builds, plain HTML first) | | B15.2′ | Fix eval on injected defects in the vendored apps: fix rate, regression rate, patch size, $/fix; compared with published LLM-repair results |
| A15.3 | ACT runner, compressed (kept, A15.1–A15.3) | | B15.3 | EARL report (kept, B15.1) |

▶ **Gate Sun 6 Dec —** fix loop: ≥ 60% of injected name/label/alt/contrast
defects fixed with **0 accepted regressions**; ACT pass rate published honestly.

## Week 16 · 7–13 Dec — WebMCP and the ACR (milestone M3)

| # | A | | # | B |
|---|---|---|---|---|
| A16.1′ | WebMCP readiness checks (registered tools, form coverage, schema validity) | | B16.1 | ACR/VPAT: all criteria rows, honest conformance values (kept, B16.1–B16.3) |
| A16.2′ | WebMCP declaration generator for forms — verified by an agent actually using the tool | | B16.2 | AI-assisted rows labelled as such; untested never "Supports" (kept, A16.2–A16.3) |

**Pair:** Rotation #4 (report generation B → A).
▶ **Gate Sun 13 Dec — M3:** ACR presentable to a compliance officer;
a generated WebMCP tool is used successfully by an agent in a demo.

## Week 17 · 14–20 Dec — Scale: the Agent Readiness Report, performance

| # | A | | # | B |
|---|---|---|---|---|
| A17.1 | Bounded crawl, caching, Docker image (kept, A17.1/B17.1–B17.2; secondary platform condensed to the image) | | B17.1′ | **Readiness scan** of a large public site list (deterministic, cheap) |
| A17.2 | Authenticated crawling, credentials never committed (kept, A17.2) | | B17.2′ | **Agent tasks on a sampled subset** (budget-capped), confirmed failures only |
| A17.3 | 25-page audit within CI budget (kept, B17.3) | | B17.3′ | Report analysis + figures |

**Pair:** Bus-factor #4.
▶ **Gate Sun 20 Dec —** report data complete and reproducible; 25-page audit
within CI budget.

## Week 18 · 21–27 Dec — BUFFER · paper and demo

⚠ Buffer first: absorb any slip here. Only then:
- Paper-style write-up of D1 (method, pre-registration, results, limits) —
  arXiv-ready.
- 3-minute demo video: agent fails on a broken page → Verity pins and confirms
  the defect → fix loop patches it → agent succeeds.

▶ **Gate Sun 27 Dec —** draft paper reviewed by both; demo recorded.

## Week 19 · 28 Dec – 3 Jan — BUFFER · docs, licences, outside install (kept)

S19.1–S19.6 as written, plus: model/provider licence and terms checked for
every model used in published results; the benchmark's data card.
▶ **Gate Sun 3 Jan —** an outside person installs and runs both `verity scan`
and `verity agent-check` from the README alone.

## Week 20 · 4–10 Jan — Public release and launch

| # | S |
|---|---|
| S20.1 | Security pass (kept) — incl. no API keys in traces, results or screenshots |
| S20.2 | Release: tagged, `pip`/`npx` installable, GitHub Action updated with `agent-check` |
| S20.3 | Publish: benchmark data + code + paper (arXiv), Agent Readiness Report, results site |
| S20.4 | Launch: Show HN, r/webdev, r/accessibility, LinkedIn, dev.to; reach out to web.dev / Chrome DevRel / WebAIM / a11y and agent communities |
| S20.5 | Kill-criteria retrospective (kept) |

▶ **Gate Sun 10 Jan —** public, installable, documented; benchmark
reproducible from a clean checkout; both engineers can explain and debug
every component.

## Gate summary (v2)

| Date | Gate | If it fails |
|---|---|---|
| Sun 1 Nov | Pilot measured cost + variance | No run budget committed |
| Sun 8 Nov | Verified injections, deterministic evaluators, pre-registration tagged | No measurement starts |
| **Sun 15 Nov** | **M1: results v1 with intervals** | **Floor < 30% → MiniWoB++ primary** |
| Sun 22 Nov | 3 agent types; hijack rate measured + reduced; honest degradation | Ship with fewer agent types; never hide gaps |
| **Sun 29 Nov** | **M2: agent-check — 0 wrong confirmations** | **Confirmations off until zero** |
| Sun 6 Dec | Fix loop ≥ 60%, 0 accepted regressions | Ship MCP tools without the loop |
| Sun 13 Dec | M3: ACR presentable; WebMCP demo | Drop WebMCP generator (keep checks) |
| Sun 20 Dec | Report data reproducible; CI budget met | Shrink report sample |
| Sun 27 Dec | Paper + demo | Blog post instead of paper |
| Sun 3 Jan | Outside install from README | Fix docs before release |
| Sun 10 Jan | Public | — |

## Cut order (fixed now — cut from the top)

1. WebMCP declaration generator (keep the checks)
2. Agent Readiness Report's agent-task sample (keep the deterministic scan)
3. browser-use agent (keep tree + screen-reader agents)
4. ACT submission (keep the measured pass rate)
5. Fix loop automation (keep the MCP server)

**Never cut:** pre-registration, injection verification, the confirmation rule,
the eval harness, the outside-person install test.

## Budget

| Item | Plan |
|---|---|
| Local models | Qwen3-8B / 14B via Ollama for bulk runs — free beyond hardware time (MiniWoB++ ~49–55% unfine-tuned) |
| Frontier API | One frontier model on a capped subset; prompt caching; **hard cap enforced by the runner** — set the cap in W10 from the pilot (suggested envelope: $150–300 total) |
| Infra | Local Docker for vendored apps; BrowserGym MiniWoB++ needs no services; WebArena only if a fallback is needed (heavy) |

## Risk register

| Risk | Likelihood | Mitigation | Owner |
|---|---|---|---|
| LLM cost overrun | Med | Pilot-sized runs; local-first; hard cap; caching | A |
| Agent variance swamps the effect | Med | Paired design, power from pilot, pre-registered N | B |
| Testbed apps break / unmaintained | Med | Vendored pinned commits in Docker; MiniWoB++/WebArena fallback | A |
| Defect injection creates a second defect | Med | Injection verification aborts the variant (A11.2′) | A |
| Prompt injection hijacks our agents | High | Security track + hardening + untrusted tagging; measured | B |
| Source mapping too hard for frameworks | High | Plain HTML + React dev builds first; MCP-only fallback | A |
| Null benchmark result | Low–Med | Pre-registered → publishable; lead launch with agent-check | both |
| iCloud-synced checkout corrupts git state | **Observed** | Move repo off Desktop before W10 | Rohan |

## Ownership and what each engineer can claim

Rotations keep both deep in both halves (bus-factor rule).

| | Rohan (A) | Nikhil (B) |
|---|---|---|
| Agents | tree agent, browser-use, MCP server, agent-check CLI | screen-reader agent, agent hardening, fix loop |
| Evals | runner, injection + verification, trace viewer | evaluators, pre-registration, statistics, fix eval |
| Interview story | "I built a reproducible agent-benchmark harness with verified ground truth and a budget-capped runner" | "I designed a pre-registered evaluation and a verifier-gated fix agent with 0 accepted regressions" |

---

# PHASE 3 — VISION PRODUCTIONISATION · W10–13 · 26 Oct – 22 Nov

> **SUPERSEDED by PLAN v2 (ADR-0005, accepted 2026-10-20).** Kept for
> history; the items v2 keeps are cross-referenced there by their original
> numbers.



*Make model output trustworthy enough to show a stranger.*

## Week 10 · 26 Oct – 1 Nov — Grounding, OCR, model loader

**Learning:** two-stage grounding (small model localises, large model
judges); VLM weakness on icon-only and small targets — precisely why
Verity never trusts a VLM for coordinates or numbers; unified memory
means serialised loading is an architectural constraint, not tuning.
**Artifact (both):** a table assigning each vision task to a model,
with justification and **an explicit statement of what each model is
never asked to do**.

| # | A | | # | B |
|---|---|---|---|---|
| A10.1 | Image inventory: every `<img>`, CSS background, `<canvas>`, inline SVG + bboxes | | B10.1 | Florence-2 region grounding; IoU measured |
| A10.2 | Screenshot storage — crops stored once and referenced | | B10.2 | OCR text-in-image (SC 1.4.5); logos excluded |
| A10.3 | Logo/decorative heuristics to cut OCR volume | | B10.3 | Single-slot model loader, LRU eviction, explicit unload |
| | | | B10.4 | Model-load timing reported separately from inference |

**Pair (90 min):** profile a full page audit — **load or inference
dominant?** The answer determines where Week 17's optimisation goes.
▶ **Gate Sun 1 Nov —** text-in-image detected; full corpus run within
the memory budget.

## Week 11 · 2–8 Nov — Alt-text judgment, constrained decoding, escapes

*The week where the fabrication trap is either handled properly or
silently baked into the product.*

**Learning:** rubric design so the model **can decline**; grammar
constraints and their documented failure mode; **constrain the shape,
not the thinking** — let it reason freely, then format the conclusion.
**Artifact (both):** write the schema linter rule **before** the schema
it governs.

| # | A | | # | B |
|---|---|---|---|---|
| A11.1 | **Schema linter** — rejects any required closed-vocabulary judgment field lacking `unknown`/`insufficient_evidence`. Runs in CI | | B11.1 | Alt-meaningfulness judge with explicit rubric → `docs/rubrics/` |
| A11.2 | Deterministic alt heuristics: filename regex, placeholder dictionary, redundancy vs adjacent text | | B11.2 | Grammar-constrained output; every judgment field nullable, every enum carries an escape |
| A11.3 | Decorative-image detection, both directions | | B11.3 | **Escape-utilisation rate as a first-class metric** |
| | | | B11.4 | Cross-check model vs heuristics; disagreement → needs-review |

**Pair:** **ADR-0008: mandatory escape values and the schema linter** —
the ADR most likely to be questioned by an outside reader.
▶ **Gate Sun 8 Nov —** **escape utilisation > 0.** At or near zero
means the model is being coerced into guessing and the schema must be
redesigned before proceeding.

## Week 12 · 9–15 Nov — Confidence calibration

**Learning:** why a raw score is not a probability; isotonic and Platt;
conformal prediction where a non-singleton set is the honest
needs-review signal; why three buckets beat per-finding percentages.
**Artifact (both):** produce a reliability diagram from Week 11 outputs
independently. **If they disagree, the split design is leaking.**

| # | A *(owns calibration since rotation #2)* | | # | B |
|---|---|---|---|---|
| A12.1 | `verity/calibration/` — isotonic fitted on a held-out injected split; curve stored, versioned by ruleset | | B12.1 | Held-out split, strict separation, **asserted in CI** |
| A12.2 | Conformal layer; non-singleton sets → needs-review | | B12.2 | **Per-SC** false-positive measurement |
| A12.3 | Three-bucket presentation; **no numeric confidence in user-facing output** | | B12.3 | FP tolerance threshold, enforced |
| A12.4 | Calibration drift detection; recalibration enforced on ruleset change | | | |

**Pair (2 hrs):** decide jointly whether AI-assisted findings meet the
bar for annotation or are demoted permanently. **ADR-0009.**
▶ **Gate Sun 15 Nov —** AI-assisted FP within tolerance **per
criterion**, not merely in aggregate.
⚠ **Phase 3 kill criterion:** if FP can't be bounded by end of this
week, AI findings become **needs-review-only, permanently**. They never
gate and never claim pass/fail. The product ships regardless.

## Week 13 · 16–22 Nov — Observability, degradation, State Explorer

**Learning:** which signals indicate *trust* health rather than
performance health; **a tool that quietly checks less than it claims is
worse than one that checks nothing.**
**Artifact (both):** independently list every partial-failure mode and
what the report must say; merge into `docs/degradation.md`.

| # | A | | # | B |
|---|---|---|---|---|
| A13.1 | `node-worker/state_explorer/` — rule-driven triggers for modals, menus, error states | | B13.1 | `verity-trace.json` — per-stage timing, cache hit rate, model load, tokens/sec, escape rate |
| A13.2 | Depth/breadth caps, per-page state budget, loop guard | | B13.2 | Graceful degradation — no GPU disables Vision/Audio; findings become needs-review, **never silently dropped** |
| A13.3 | State labelling + hashing so findings attribute to the right state | | B13.3 | Report coverage section: exactly what was and wasn't checked, and why |
| | | | B13.4 | `render_failed` — one broken page doesn't abort a 25-page audit |

**Pair:** **Bus-factor #3**, then **Rotation #3: Interaction Agent
A → B.**
▶ **Gate Sun 22 Nov —** kill the model backend mid-run; the tool
completes and the report accurately states what was not checked.

---

# PHASE 4 — EVALUATION & CREDIBILITY · W14–17 · 23 Nov – 20 Dec

*In a trust-based category, the credibility of the evaluation **is**
the product.*

## Week 14 · 23–29 Nov — Full fault-injection harness

**Learning:** why synthetic injection is the primary strategy;
prevalence weighting (an unweighted corpus produces a number that is
arithmetically correct and practically meaningless); **injection
verification** — injecting one defect can mask or create another, and
silently wrong ground truth makes every downstream number wrong.
**Artifact (both):** the full injection table with prevalence weights
from published field data. **This table drives every headline metric
the project will publish.**

| # | A | | # | B |
|---|---|---|---|---|
| A14.1 | Complete injector set to ~15 types — six highest-prevalence categories plus interaction and target-size | | B14.1 | `eval/` harness — per-SC precision, recall, F1, reproducible with one command |
| A14.2 | **Injection verification pass** — assert exactly the intended defect appeared and no second one. Failure aborts corpus generation | | B14.2 | Baseline vs axe-core alone — recall strictly exceeds at equal or lower FP |
| A14.3 | Prevalence-weighted corpus generator | | B14.3 | Coverage metric: fraction of 86 criteria attempted, by modality, **published honestly including gaps** |
| | | | B14.4 | Baseline freeze → `eval/baselines/<version>.json`; regressions fail CI |

**Pair (2 hrs):** write the README's honest-limitations section from
these numbers. Where a competitor figure can't be reproduced, **say so
and describe the methodology gap** rather than implying parity.
▶ **Gate Sun 29 Nov —** per-criterion precision and recall reproducible
from a clean checkout; a deliberately introduced regression fails CI.

## Week 15 · 30 Nov – 6 Dec — ACT test cases and implementation report

*The cheapest credibility available to an unknown open-source tool.*
**Artifact (both):** hand-write one EARL assertion before generating
any.

| # | A | | # | B |
|---|---|---|---|---|
| A15.1 | ACT test-case runner — corpus mirror, each case in isolation, unattended | | B15.1 | EARL JSON-LD report generator |
| A15.2 | Outcome mapping incl. **honest use of `cantTell`** | | B15.2 | Triage top failing rules; fix what's cheap, document the rest as known gaps |
| A15.3 | Per-rule pass-rate reporting | | B15.3 | Decide jointly: submit in Week 20 or defer |

**Pair:** **ADR-0010** — submit or defer, with the measured pass rate
recorded either way.
▶ **Gate Sun 6 Dec —** ACT pass rate measured and published honestly,
**whatever the number is**.

## Week 16 · 7–13 Dec — VPAT / ACR generation

**Artifact (both):** fill one complete ACR row by hand — criterion,
conformance value, remarks — before automating anything.

| # | A *(takes report generation at rotation #4)* | | # | B |
|---|---|---|---|---|
| A16.1 | ACR generator, WCAG edition, **all 86 criteria — every one gets a row, including untested** | | B16.1 | Conformance mapping to the four values |
| A16.2 | Every AI-assisted row labelled *"AI-assisted finding — requires human verification"* | | B16.2 | Remarks: plain-language, evidence reference, remediation pointer — readable by a non-engineer |
| A16.3 | Untested criteria marked honestly, **never defaulted to Supports** | | B16.3 | Static standards mapping table — 86 rows |

**Pair:** review the generated ACR as though received from a vendor —
*would you trust it?* Then **Rotation #4: report generation B → A**.
**Decision point:** the Bible flags the standards-mapping fuzzy
fallback as a deletion candidate. With the table now built — does the
fallback path ever actually fire? If not, delete it.
▶ **Gate Sun 13 Dec —** the ACR is presentable to a compliance officer
without embarrassment or manual correction.

## Week 17 · 14–20 Dec — Caching, crawl bounding, performance

**Artifact (both):** independently identify every input that should
invalidate a cache entry. **A missed invalidation produces stale
findings — a correctness bug wearing a performance costume.**

| # | A | | # | B |
|---|---|---|---|---|
| A17.1 | Bounded crawl frontier, all configured limits enforced | | B17.1 | Content-addressed cache; unchanged page states skipped entirely |
| A17.2 | Authenticated crawling via stored session state, path-referenced, **never committed**; credentials scrubbed from traces and screenshots | | B17.2 | Findings cached per (ruleset version, content hash) |
| A17.3 | Viewport matrix — findings attributed to the correct viewport | | B17.3 | Full-audit performance on a 25-page site |
| | | | B17.4 | Serialised model queue tuning, informed by the Week 10 profile |

**Pair (2 hrs):** **Bus-factor #4** across all four rotated modules.
*This is the last scheduled one and should be the easiest — if it
isn't, that is important information about where the documentation is
still thin.*
▶ **Gate Sun 20 Dec —** a 25-page audit completes within a realistic CI
budget; an unchanged re-run is materially faster.

---

# PHASE 5 — LAUNCH · W18–20 · 21 Dec – 10 Jan

⚠ **Weeks 18–19 are the project's only designated buffer.** If earlier
phases slipped, absorb it here rather than adding weeks. **Do not spend
this buffer on scope.**

## Week 18 · 21–27 Dec — Secondary platform and remediation text

| # | A | | # | B |
|---|---|---|---|---|
| A18.1 | Container image for the secondary platform | | B18.1 | Secondary-platform serving path for vision and ASR |
| A18.2 | CI matrix covering both platform targets | | B18.2 | Remediation phrasing via a small local model, **template fallback when unavailable — never empty output** |

▶ **Gate Sun 27 Dec —** the same corpus produces identical findings on
both platform targets.

## Week 19 · 28 Dec – 3 Jan — Documentation and license ledger

| # | S |
|---|---|
| S19.1 | **License ledger verified, not assumed** — every dependency and every model weight, actual licence text read → `docs/licenses.md`. Anything unverified marked unverified |
| S19.2 | Permissive-weights fallback configuration, tested end-to-end |
| S19.3 | Complete README in the prescribed order, no placeholders |
| S19.4 | Honest limitations table — what Verity does not test, and why |
| S19.5 | Contributing guide incl. the mandatory rule-pack fixture requirement |
| S19.6 | Plugin sandboxing — community rules in a restricted subprocess, no network, read-only FS except temp |

▶ **Gate Sun 3 Jan —** a person outside the project installs and runs
Verity from the README alone. **Test on an actual outside person — not
on each other.**

## Week 20 · 4–10 Jan — Public release

**Learning (both, 60 min):** write the project narrative jointly — the
problem, the trust-partitioning insight, what the measured results
actually show, and what you would do differently.

| # | S |
|---|---|
| S20.1 | Final security pass — no credentials in artifacts, traces, or screenshots; dependency audit clean |
| S20.2 | Public repository release, tagged, installable from the published artifact |
| S20.3 | ACT implementation report submitted per the Week 15 decision |
| S20.4 | **Kill-criteria retrospective** — which fired, which did not, what the pre-set bars would have caught → `docs/retrospective.md` |
| S20.5 | Final bus-factor verification across the whole system |

▶ **Gate Sun 10 Jan —** Verity is public, installable, and documented,
and **both engineers can explain and debug every component**.

---

# Gate summary

| Date | Gate | Consequence of failure |
|---|---|---|
| Sun 16 Aug | First authoritative finding end-to-end | Slip one week; skeleton is prerequisite for everything |
| **Sun 23 Aug** | **Vision precision meets pre-set bar** | **Descope Vision to OCR + contrast; rewrite Phases 3–5** |
| Sun 6 Sep | Beat axe on contrast-over-image at zero new FP | Wedge one unproven; reassess differentiation |
| Sun 13 Sep | Trap detected, zero false alarms | Tune N; do not proceed with false alarms |
| Sun 20 Sep | Phase 1 demoable; bus-factor passed | Fix documentation before Phase 2 |
| Sun 4 Oct | No finding can exist without provenance | Blocking — the type invariant is the product |
| Sun 11 Oct | Baseline gating isolates new findings | Blocking — adoption impossible without it |
| Sun 18 Oct | PR annotations on a demo repo | The first useful thing isn't shippable; stop and fix |
| Sun 25 Oct | Five APG contracts pass; misuse fails | Reduce to three; do not ship false alarms |
| Sun 1 Nov | Text-in-image works; memory within budget | Reduce model size or drop the task |
| **Sun 8 Nov** | **Escape utilisation > 0** | **Schema redesign required before proceeding** |
| **Sun 15 Nov** | **AI-assisted FP within tolerance per criterion** | **AI findings become needs-review-only, permanently** |
| Sun 22 Nov | Honest degradation under forced failure | Blocking — silent under-checking is disqualifying |
| Sun 29 Nov | Metrics reproducible; regressions fail CI | Blocking — **never cut the eval harness** |
| Sun 6 Dec | ACT pass rate published | Ship anyway; do not claim conformance |
| Sun 13 Dec | ACR presentable to a compliance officer | Iterate; this is the buyer-facing artifact |
| Sun 20 Dec | 25-page audit within CI budget | Pull optimisation into the buffer weeks |
| Sun 27 Dec | Identical findings across platforms | Ship single-platform; document the limitation |
| Sun 3 Jan | Outside person installs from README alone | Fix docs before release |
| Sun 10 Jan | Public and documented | — |

# Scope control

## The deferred list — re-read at every Sunday gate

| Deferred | Reason |
|---|---|
| Real screen-reader automation in CI | Fragile; virtual SR + accname is a better engineering choice |
| Audio description testing (1.2.3 / 1.2.5) | Not reliably detectable — do not pretend otherwise |
| SC 3.3.7, 3.3.9, 3.2.6 | Manual or process-level |
| WCAG 3 / APCA as pass-fail | Not standardised; advisory only |
| Multi-engine corroboration | Phase 2 of the product, not of this build |
| APG patterns beyond the core five | Diminishing returns before launch |
| State exploration beyond bounded modals/menus | Combinatorial risk |
| INT edition ACR | WCAG edition first |

## The slip rule

**When a gate slips two weeks, pull an item off the deferred list
forward — meaning cut scope — rather than extending the timeline.**

The failure mode this guards against is specific and predictable:
somewhere around month three, adding a seventh success criterion will
feel cheap and obvious. Then an eighth. That is the mechanism by which
a five-month project becomes a nine-month one, and it does not feel
like a mistake at any individual step.

**Never cut the evaluation harness.** It is the only thing standing
between this project and shipping a tool that lies about its own
accuracy.

## What survives if the vision spike fails

axe-core wrapper for the authoritative floor, plus contrast-over-image
adjudication, plus keyboard interaction testing against APG contracts.
That combination remains genuinely novel, addresses the largest
documented coverage gap, and no free self-hostable tool does it well.

**The vision model is deliberately not the load-bearing wall of the
architecture. The differentiator degrades; it does not disappear.**

---

# Best-in-class backlog — competitive differentiation

> **2026-10-20:** BC-C2 (benchmark) is done; PLAN v2 turns BC-B2/BC-B4 and
> the C-section distribution strategy into scheduled work (D1–D4).

> **Added 2026-10-18**, from a competitive analysis of the top tools in this
> space (axe-core, Lighthouse, Pa11y, IBM Equal Access, Microsoft
> Accessibility Insights, and the commercial tier: axe DevTools Pro,
> Siteimprove, Level Access). Source notes: `docs/competitive-analysis.md`.

**The strategic finding.** Almost every "competitor" runs on the *same engine*
— axe-core sits under axe DevTools, Lighthouse, Accessibility Insights,
Siteimprove and Pa11y — and automated engines catch only ~30–57% of WCAG by
their own vendors' numbers. The entire market is crowded onto one library that
misses roughly half of WCAG. **Verity's reason to exist is the other half:**
the cases axe marks `incomplete` (contrast-over-image) or cannot test at all
(keyboard operability, focus order, traps), resolved by a system that is
*honest about what it does not know and never fabricates*.

**This backlog does not override the 20-week plan or its scope control.** The
gated plan ships 1.0 first; the deferred list and the slip rule still stand.
Items are classified by *when*, and the few that contradict an existing
deferral are called out as such rather than quietly slipped in.

## A — Pull forward (in current scope: integration gaps, not new scope)

These are not new features — they are gaps between "built" and "wired", or
cheap recall wins already sanctioned by an ADR. They make the differentiators
we already paid for actually show up in a scan.

| # | Track | Task | Why now |
|---|---|---|---|
| BC-A1 | B | **Wire `traverseTabOrder` into `scan_url()`** | The entire keyboard wedge (A4.x + B4.x) is built and tested but never invoked by a real scan — a `verity scan` emits zero keyboard findings today. Highest-ROI item in the repo; the headline differentiator is dark until this lands. |
| BC-A2 | A | **Close the 3.0–4.5 contrast band** — add `fontSize`/`fontWeight` to `sampleRegion` so the adjudicator applies the correct threshold per node | Pure recall win over axe; ADR-0003 already sanctioned it as a deferred Track-A change, not a new decision. |
| BC-A3 | A+B | **Verify the Week-8 SARIF annotation gate for real** — a PR on a repo with code scanning enabled, confirming inline annotations render | Already the Sun 18 Oct gate; `sarif-reference.md` §6 flags it as the one thing never verified. "The first useful thing" is unproven until this is seen working once. |

## B — Phase 2 / post-1.0 differentiation (respects the deferred list)

Genuine new scope. Deliberately **not** pulled into the 20-week build, because
the slip rule and the "adding a seventh success criterion feels cheap" warning
apply directly here. Recorded so the direction is explicit, and scheduled after
1.0 or into Phase-2 buffer weeks — never by extending the timeline.

| # | Track | Task | Note vs. existing scope |
|---|---|---|---|
| BC-B1 | A+B | **APG contracts beyond the core five** — menu, menubar, radiogroup, tree, grid, listbox, combobox, dialog | **Contradicts the deferred-list entry "APG patterns beyond the core five — diminishing returns before launch."** Kept deferred until 1.0 ships; listed here as the top post-launch coverage moat because the contracts are declarative YAML and compound. |
| BC-B2 | A+B | **New measurable SCs:** reflow at 400% (1.4.10), text-spacing (1.4.12), target size (2.5.8, WCAG 2.2), `prefers-reduced-motion` | Each is a new success criterion — the exact scope-creep the slip rule warns about. Post-1.0 only, one at a time, each with its own pre-set precision bar. |
| BC-B3 | A | **`verity-core` as an embeddable library + Playwright/Cypress/Jest matchers** | Distribution, not detection. axe-core's reach *is* its embeddability; this is how Verity gets embedded rather than only run. |
| BC-B4 | A+B | **Hosted "scan any URL" playground** — Verity's honest report vs axe's `incomplete`s, side by side | The single best conversion surface; also the artifact behind the comparison benchmark below. |
| BC-B5 | B | **Accelerate VPAT / ACR generation** (already S16.x) and treat it as a headline feature | Already in-plan at Week 16 — flagged here because it is the one output *buyers* need and no OSS tool produces well. Do not cut it under slip pressure. |

## C — Distribution / "most-starred" strategy (non-code, ongoing)

Stars come from distribution and narrative, not from being technically best
(Lighthouse's ~28k is from shipping inside Chrome; axe-core's ~7k from being
embedded everywhere). These are marketing/positioning tasks, owned jointly.

| # | Task |
|---|---|
| BC-C1 | **Own one story:** *"the accessibility engine that refuses to lie"* — lead every README/post with the provenance + never-fabricate doctrine. It is a unique position in a market of tools that quietly guess. |
| BC-C2 | **A reproducible, honest benchmark** — "Verity resolves the keyboard trap and the contrast-over-image that axe/Lighthouse mark `incomplete`", with the fixtures and numbers public. |
| BC-C3 | **Zero-friction trial** — the one-line GitHub Action (shipped) + the playground (BC-B4). |
| BC-C4 | **Lower the contribution bar** — good-first-issues for new APG contracts (declarative YAML), a public roadmap, and the Contributing guide (S19.5). Contributors become evangelists. |

> **Guardrail.** Nothing in sections B and C may pull a 20-week gate's work
> forward or displace the evaluation harness. If a best-in-class item starts
> competing with a gated deliverable, the gated deliverable wins — the plan
> ships a trustworthy 1.0 first, and differentiation compounds on top of it.
