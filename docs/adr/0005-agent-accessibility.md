# ADR-0005: Phases 3–5 pivot to agent accessibility

**Status:** ACCEPTED (2026-10-20)
**Date:** 2026-10-20
**Proposed by:** Rohan Arekatla · **Agreed:** Nikhil
**Supersedes:** the vision-productionisation scope of Phases 3–5 in
`execution-plan.md` (Weeks 11–13 vision items; parts of 14–18). ADR-0002
(vision descoped to an experiment) stays in force.

## Context

Three things are true on 20 Oct 2026 that were not when the plan was written.

1. **Vision did not earn its place.** Spike A (ADR-0002): the model abstained
   on 79% of cases. Phase 3 as written spends four weeks productionising a
   capability that measured near-zero recall.
2. **Verity's deterministic core is now provably ahead.** The BC-C2 benchmark
   (`docs/measurements/benchmark-2026-10-19.md`): on text over images Verity
   decided 202/202 true failures with 0 false; axe and Pa11y sent all 202 to
   review, Lighthouse missed all 202 silently. On keyboard/widget defects
   Verity caught 7/7, every other tool 0/7.
3. **The accessibility tree became the interface AI agents use.** Google's
   web.dev lists it as one of the three ways agents perceive a page; Chrome
   calls a well-formed tree the primary way agents understand it; Playwright
   MCP is tree-based; OpenAI says ChatGPT Atlas reads ARIA. Chrome shipped a
   Lighthouse "Agentic Browsing" category in June 2026 — **static, and
   described by Chrome as "informational and unbenchmarked."** WebMCP (Google +
   Microsoft, W3C CG) is in origin trial.

And one gap nobody has filled: **there is no controlled measurement of
whether WCAG defects change AI-agent task success.** The closest work
(LCoW, observation-reduction studies, VisualWebArena) shows that page
*representation* affects agents — never that a missing label or a div-button
does, by how much, or for which kind of agent. Practitioner articles assert
the link without data.

Verity already owns the two hardest parts of answering it: **controlled defect
injection** (eval/inject, ARIA-misuse injectors) and a **ground-truth
verifier** with zero false alarms on its benchmarks.

## Decision

Re-scope Phases 3–5 around one thesis — **accessibility for people and for AI
agents is the same engineering problem, and Verity measures both** — in four
deliverables, in priority order:

1. **The Agent Accessibility Benchmark** — the first controlled, pre-registered
   study of how WCAG defects change web-agent task success, across agent types
   (tree-only, DOM+vision, screen-reader simulation) and models (frontier and
   local open-weight). Published with data, code and a paper-style write-up.
2. **`verity agent-check`** — run a real LLM agent on a site's task through the
   accessibility tree and keyboard only; every failure is localised to a step
   and **confirmed by a deterministic Verity check**, or reported as
   needs-review. Two scores: WCAG and agent-readiness.
3. **Verifier-gated remediation** — Verity as an MCP server for coding agents;
   a fix loop whose patches are accepted only when Verity proves the defect gone
   and the baseline shows no regression; WebMCP readiness checks and
   declarations.
4. **The Agent Readiness Report** — deterministic agent-readiness scan of a
   large public site list plus real agent tasks on a sample; released at launch.

Kept from the original plan, because they are the product's credibility:
the fault-injection harness (W14, now the benchmark's core), degradation and
observability (W13), ACT implementation report (W15, compressed), ACR/VPAT
(W16), caching/crawl bounding (W17), licence ledger, docs and outside-person
install test (W19), release (W20), the two buffer weeks, and every kill
criterion's spirit.

Cut: alt-meaningfulness VLM judge (B11.1–B11.4 as written), isotonic/conformal
calibration of vision outputs (W12 as written), secondary-platform vision/ASR
serving (B18.1), Week 10 OCR/grounding as a gating item (kept optional behind
the ADR-0002 flag).

The doctrine does not change: **the model proposes, the maths decides.** An
agent's failure is never reported as a site defect unless a deterministic
check confirms the barrier; a fix is never accepted unless Verity proves it.

## Consequences

**Good.** The project's AI work becomes agents + evals + tool design + agent
security — the skills 2026 AI-engineer hiring screens for — and rests on the
deterministic core instead of on a model that failed its spike. The benchmark
is a novel, citable result; the CLI is a one-command, any-provider tool.

**Costs and risks** (each with a gate in the plan):
- LLM spend. Bulk runs on local open-weight models (Qwen3-8B/14B score ~49–55%
  on MiniWoB++ unfine-tuned); frontier models on a capped subset. Hard budget
  cap enforced by the runner.
- Agent nondeterminism. Repeated trials, paired designs, pre-registered
  hypotheses and confidence intervals; no single-run claims.
- Testbed fragility. Pinned, vendored app commits; BrowserGym (MiniWoB++,
  WebArena) as the standard fallback.
- Prompt injection: pages are untrusted input to our agents. A security track
  measures and hardens it (WASP-style cases), and agent-check never lets page
  content change its task or tools.
- Scope. Cut order is fixed in advance (plan v2, "cut order").

**Kill criteria** (pre-set, as ADR-0002 did):
- **Benchmark floor:** if clean-page success for the best model is < 30% on the
  task suite after W12, the effect is unmeasurable there — switch the primary
  suite to MiniWoB++ and the vendored apps' simplest tasks.
- **Null result is still a result:** if injected defects show no significant
  effect, publish that (pre-registration makes it credible) and lead the launch
  with agent-check's verified localisation instead.
- **agent-check precision:** if a confirmed failure is ever wrong on the
  injected corpus, confirmation logic is blocking; nothing ships confirmed until
  it is zero.

## Signatures

- Rohan Arekatla — proposed 2026-10-20
- Nikhil — agreed 2026-10-20 (in conversation with Rohan; relayed by Rohan). Nikhil to add a written confirmation line here or on PR #32.
