# ADR-0003: The model localises, the math decides

**Status:** DRAFT — context written by B, decision to be agreed and signed jointly.
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

> _To agree jointly. Proposed wording:_
>
> **A model may never produce a value that determines a verdict.** Models may
> localise, classify, and abstain. Numbers that decide conformance come from
> deterministic computation over measured inputs.
>
> Concretely: no schema handed to a model may contain a ratio, a threshold, a
> score, or a pass/fail field. Where a model's output feeds a calculation, the
> calculation is performed in Python over values the browser reported.

---

## Consequences

> _To write jointly. Starting points:_
>
> - Vision work is bounded in advance: every future judgment must be
>   expressible as "point at it" or "classify it", never "measure it".
> - Deterministic paths may gate a build; model-assisted ones may not. This
>   is already enforced in `cli.py`, which exits non-zero only on
>   `AUTHORITATIVE` findings.
> - Adding a measurement means adding it to the *worker*, not the model —
>   as `sampleRegion` did for contrast.

---

## Alternatives rejected

> _To write jointly._
>
> - **Let the model report the ratio and validate it afterwards.** Rejected:
>   there is nothing to validate against without measuring the pixels, at
>   which point the model's number is redundant.
> - **Use the model's bounding box, then sample inside it.** Not rejected —
>   deferred. This is the intended path for cases where the DOM gives no
>   usable selector. It still obeys the principle, because the model supplies
>   coordinates and the maths supplies the verdict.
