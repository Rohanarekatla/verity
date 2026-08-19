# ADR-0002: Spike A — whether Vision stays in scope

**Status:** DRAFT — decision pending the Saturday 22 Aug pair session.
**Date:** _pending_
**Signed:** Nikhil ____ / Rohan ____ (both must sign — see team-plan §2.6)

> This draft carries the Context section only. The Decision is deliberately
> blank: it cannot be written until the corpus has been run against a wired
> model, and it must be made **jointly**.

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

> _To be written Saturday 22 Aug, jointly. One of:_
>
> - **Vision stays in scope** — bar met on both precision and latency.
> - **Vision descoped to experiment** — behind a flag, not a shipped
>   feature; project continues on the deterministic + contrast-maths path.
> - **Vision stays, caching pulled forward** — precision met, latency
>   between the soft and hard bars; Week 17's caching work moves earlier.

_Result against the bar:_

| Measure | Bar | Actual | Met? |
|---|---|---|---|
| Precision (point estimate) | | | |
| Precision (95% CI lower bound) | | | |
| Abstention rate | | | |
| Median page latency | | | |
| p95 page latency | | | |

---

## Consequences

> _To be written with the decision._

---

## Alternatives rejected

> _To be written with the decision. At minimum, record why the bar was not
> set lower once the results were known — or, if it was renegotiated, say so
> openly and say why. A bar quietly moved after the fact is the failure mode
> this whole ritual exists to prevent._
