# ADR-0002: Spike A — whether Vision stays in scope

**Status:** ACCEPTED
**Date:** 2026-10-18 (Context 30/08/2026; Decision written after the Spike A run, signed off late)
**Signed:** Nikhil (proposed / authored Context) / Rohan Arekatla (agreed 2026-10-18)

> The Context was written in Week 2; the Decision could not be until the corpus
> had run against a wired model. It has now (see
> [`../measurements/spike-a.md`](../measurements/spike-a.md)), so the Decision
> below is written against real numbers, not a prediction.

---

## Context

Week 2 is a risk gate. The question it exists to answer:

> *Can an 8B open vision model make accessibility judgments without
> generating false positives?*

If the answer is no, the project continues in reduced form — but
**knowingly**. That word is the whole point of the spike. Shipping a vision
feature that quietly fabricates is worse than not shipping one.

### What was built

**Track B (Nikhil)** — three judgments, each a Pydantic schema for
constrained decoding plus a rubric used as the system prompt:

| Task | Judgment | Schema | Rubric |
|---|---|---|---|
| B2.2 | alt-text meaningfulness | `AltTextJudgment` | `ALT_TEXT_RUBRIC` |
| B2.3 | focus-visible, before/after | `FocusVisibleJudgment` | `FOCUS_VISIBLE_RUBRIC` |
| B2.4 | contrast-region localisation | `ContrastRegionLocalisation` | `CONTRAST_LOCALISATION_RUBRIC` |

All three can abstain. `ContrastRegionLocalisation` returns bounding boxes
only and has no field in which a contrast ratio could be reported.

B2.5 records end-to-end latency into `AuditReport.latency`.

**Track A (Rohan)** — element-level screenshot capture with boxes in CSS and
device pixels (A2.1, A2.2), and the Spike A corpus harness (A2.3).

### Constraints discovered during the week

These are recorded here because they change what the gate measures, and they
should be visible in the decision rather than discovered afterwards.

**1. Focus-visible cannot be measured this week.** Nothing in `node-worker`
captures a focused screenshot — that capability is A4.3 (Week 4), and the
`outline_none` injector is B4.3 (Week 4). The corpus has three injectors
(`strip_alt`, `detach_label`, `reduce_contrast`), none of which produce focus
states. So the precision number covers **two of three** judgments. B2.3
carries forward to Week 4.

**2. The corpus is 117 usable cases, not ~200.** 197 are structurally valid;
117 are confirmed detected and therefore scoreable. Split across two
measurable judgments, that is roughly 50–60 cases each — which is why the
proposed bar is stated as a confidence-interval lower bound rather than a
point estimate. See [`../measurements/precision-bar.md`](../measurements/precision-bar.md).

**3. Precision alone is gameable.** A model that always abstains scores 100%
precision on zero findings. The bar therefore pairs a precision floor with an
abstention ceiling.

**4. Latency is an independent gate.** A page that takes 90 s means "runs in
CI" is quietly false, regardless of how accurate the findings are.

### The bar

Agreed and written down before results existed:
[`../measurements/precision-bar.md`](../measurements/precision-bar.md).

---

## Decision

**Vision is descoped to an experiment.** It lives behind a flag, off by
default, and is not a shipped feature. The product continues on the
deterministic + contrast-maths path that Weeks 1–4 built (axe-core,
pixel-sampled contrast adjudication, keyboard traversal).

This is the middle option, and it is chosen **knowingly** — which is the whole
point of the spike. The bar was set before results existed; the results did
not meet it; we are not moving the bar to fit them. A model that abstained on
79% of cases and produced zero verdicts across 48 alt-text cases has not
demonstrated it can make accessibility judgments at the precision the product
requires. It also has not *failed dangerously* — it abstained rather than
fabricated, which is the safe direction — so "experiment, behind a flag" is
honest: the capability is not dead, it is unproven, and shipping it as if it
were proven is the one thing this ritual exists to prevent.

Two measured caveats keep this from being a verdict on vision in general, and
both are recorded rather than buried:

- The run used a **7B-4bit proxy on an M4/16 GB, not the specified 8B build**
  (Engineer B's compute constraint — see the mlx-vlm backend work). A stronger
  model may abstain less.
- **Two of three judgments were unmeasurable this week.** Focus-visible (B2.3)
  had no focused screenshot to score until A4.3 landed — which it now has, so
  that judgment becomes measurable for the first time in Phase 3. The
  contrast-localisation set was never labelled.

So the experiment is not shelved, it is **gated on a re-run**: the flag stays
off until vision is re-measured against the bar on (a) the intended model and
(b) the now-measurable focus-visible judgment. Until then, nothing in a shipped
report depends on a model — consistent with ADR-0003.

_Result against the bar (alt-text, B2.2; measured 2026-08-18, 7B-4bit
stand-in on M4/16 GB — see [`../measurements/spike-a.md`](../measurements/spike-a.md)):_

| Measure | Bar | Actual | Met? |
|---|---|---|---|
| Precision (point estimate) | ≥ 0.95 | n/a — 0 findings | — |
| Precision (95% CI lower bound) | ≥ 0.90 | n/a — 0 findings | — |
| Recall on placeholders | secondary | 0 / 36 | ✗ |
| Abstention rate | ceiling | 79% | ✗ |
| Per-judgment latency | — | 5.0 s mean / 10.5 s max | — |

**The model produced zero `no` verdicts across 48 cases — it abstained
rather than fabricated.** Precision is undefined because there are no
findings to be precise about; the failure is on recall and abstention,
not false positives. Focus-visible (B2.3) and a labelled contrast-
localisation set were not measurable this week (see Context). The number
above is from a 7B-4bit proxy, not the specified 8B build.

---

## Consequences

- **No shipped finding depends on a model.** The product's trust story stays
  simple: everything that can fail a build is deterministic. This is the same
  commitment ADR-0003 makes from the other direction, and the two should be
  read together.
- **The Bible's claims are trimmed to match.** Any marketing or README line
  implying shipped AI accessibility judgment comes out until the re-run
  clears the bar. We describe vision as experimental, flag-gated, and
  unproven — because it is.
- **The vision code is kept, not deleted.** Schemas, rubrics, the mlx-vlm
  backend and the three judgments stay in-tree behind the flag. The spike's
  value is the measurement, and throwing the code away would mean re-running
  the spike from scratch to revisit the decision.
- **A4.3 changes what is measurable.** Focus-visible now has a real signal
  (the worker's computed-style diff), so the Phase-3 re-run can score two
  judgments, not one. That materially changes the evidence the next decision
  rests on.
- **The kill criterion still stands.** Phase 3's own gate (Week 12) says if
  false positives can't be bounded, vision is cut entirely. This ADR does not
  pre-empt that; it just refuses to ship vision *before* that gate.

---

## Alternatives rejected

- **Vision stays in scope.** Rejected: the bar was not met on either recall or
  abstention, and precision was undefined because there were no findings to be
  precise about. Shipping would be claiming a capability the measurement does
  not support.
- **Lower the bar to match the result.** Explicitly rejected, and recorded
  here because this is the exact failure the ritual guards against. The bar
  (precision floor + abstention ceiling) was agreed in writing *before* the
  run, for the stated reason that a precision number alone is gameable by a
  model that always abstains — which is precisely what happened. Moving the
  bar now would retrofit success onto a result that did not earn it. We did
  not renegotiate it; we recorded that it was not met.
- **Cut vision entirely.** Rejected *for now* — the abstain-not-fabricate
  behaviour and the two unmeasured judgments mean the capability is unproven,
  not disproven, and the measured caveats (proxy model, unmeasurable
  focus-visible) are concrete reasons the next run could differ. Deleting it
  would discard the spike's investment before the evidence is actually in.
  Week 12's kill criterion is where "cut entirely" gets decided on bounded-FP
  evidence.

---

## Rohan's sign-off note

Agreed. I'd have been uncomfortable signing "stays in scope" on these numbers,
and equally uncomfortable with "cut entirely" while B2.3 was literally
unmeasurable — which was partly my gap, since the focused-screenshot capture
(A4.3) didn't exist until Week 4. "Descoped to experiment, gated on a re-run"
is the reading I can defend: it's honest about the failure, it doesn't throw
away the measurement, and it ties the comeback to a concrete, now-satisfiable
precondition rather than to optimism.
