# ADR-0003: The model localises, the math decides

**Status:** PROPOSED — decision drafted by B, awaiting Rohan's agreement and both signatures.
**Date:** _pending_
**Signed:** Nikhil ____ / Rohan ____ (both must sign — see team-plan §2.6)
**Week:** 3 (31 Aug – 6 Sep)

> Overdue. This should have been written during Week 3's pair session and
> was not. The context below is what actually shipped; the Decision and
> Consequences need agreeing together.

---

## Context

axe-core returns four buckets, and one of them is `incomplete` — cases where
axe explicitly declines to judge. The dominant cause is text on a background
image: axe reads the text colour from CSS but cannot read a photograph, so it
returns no verdict at all.

Until Week 3 we forwarded that shrug to the user as "needs review". Honest,
but useless — the user still had to open a colour picker.

Week 3 resolved those cases. The question this ADR settles is **how**, because
there were two plausible routes and only one of them is defensible.

### The two routes

**Route A — ask the vision model.** Show the model a crop, have it report
where the text is and what colour it is, compute or accept a ratio.

**Route B — read the actual pixels.** The browser already rendered the page.
Ask it for the real colours, then apply the WCAG formula.

We took Route B. Chromium has the exact pixels; asking a model to estimate
what the browser can state exactly adds a source of error and nothing else.

### Where the model still has a role

Not nowhere — but strictly bounded. `ContrastRegionLocalisation` (B2.4) lets
a model say *where* text is when nothing else can. It has **no field in which
a ratio, a colour, or a pass/fail could be reported**, and a `model_validator`
prevents it claiming a location it did not find.

That is the principle in one line:

> **The model localises. The math decides.**

A vision model is decent at "the text is roughly here". It is bad, and
crucially *unaccountable*, at "the contrast is 3.1:1" — a fabricated ratio is
indistinguishable from a measured one once it is in the JSON.

### What shipped

- `worst_case_ratio()` — the minimum ratio across the background sample set,
  not the average. Text on a gradient is only as readable as its worst pixel.
- `adjudicate_contrast()` — wired into `scan_url()`; `incomplete` nodes become
  `authoritative` verdicts where the arithmetic is unambiguous.
- Four refusal branches, each with a reason code.
- `sampleRegion` on the RPC surface (A3.1–A3.4).

### The one asymmetry worth recording

`RegionSample` carries no font size, and SC 1.4.3 needs 4.5:1 for normal text
but only 3:1 for large. So the adjudicator decides only where both thresholds
agree — `>= 4.5` pass, `< 3.0` fail, and the band between them stays
`cantTell`. Assuming 4.5 there would flag compliant large text as a failure,
which is the one thing the Week 3 gate forbade.

That band is a gap in the *input*, not the maths. Closing it is a Track A
change (add `fontSize`/`fontWeight`), not a change to this principle.

---

## Decision

**A model may never produce a value that determines a verdict.**

Models may localise, classify, and abstain. Every number that decides
conformance comes from deterministic computation over measured inputs.

Three rules follow, and they are testable:

1. **No schema handed to a model may contain a ratio, a threshold, a score,
   or a pass/fail field.** Not "should not populate" — the field does not
   exist, so a model that wanted to fabricate one has nowhere to put it.
2. **Where a model's output feeds a calculation, the calculation runs in
   Python over values the browser reported.** The model may supply
   coordinates; it may not supply the colours found at those coordinates.
3. **A finding whose verdict depended on a model may not be
   `AUTHORITATIVE`.** It is `AI_ASSISTED` at best, and `cli.py` never gates a
   build on it.

> _Rohan — this is B's proposed wording, not an agreed decision. Change it,
> narrow it, or argue with it; it is not ready until we both sign._

---

## Consequences

- **Vision work is bounded in advance.** Every future judgment must be
  expressible as "point at it" or "classify it", never "measure it". If a
  capability cannot be phrased that way, it is a worker feature, not a model
  feature.
- **Adding a measurement means adding it to the worker.** `sampleRegion`
  (A3.4) is the template: the browser already knows the answer, so ask it
  rather than asking a model to estimate.
- **Some recall is permanently given up.** The 3.0–4.5 contrast band stays
  `cantTell` rather than being resolved by a model guessing at font size.
  This is the cost of the rule and we are accepting it knowingly.
- **`test_contrast_localisation_never_carries_a_ratio` enforces rule 1** and
  should be copied for any future model schema.

---

## Alternatives rejected

- **Let the model report the ratio, then validate it.** Rejected: there is
  nothing to validate against without measuring the pixels — and once you
  have measured them, the model's number is redundant. Validation here is
  indistinguishable from doing the work twice.
- **Let the model report the ratio with a confidence score, and gate on
  confidence.** Rejected: a fabricated ratio arrives with a confident score
  attached. Spike A's measured result — the model abstaining on 79% of cases
  rather than guessing — is what a *well-behaved* small model looks like;
  we should not build a mechanism that only works if every model behaves
  that well.
- **Use the model's bounding box, then sample inside it.** *Not rejected —
  deferred.* This is the intended path where the DOM offers no usable
  selector, and it obeys the rule: the model supplies coordinates, the maths
  supplies the verdict. Needs its own ADR when it lands, because "a wrong box
  points the sampler at the wrong pixels" is a failure mode this ADR does not
  cover.
