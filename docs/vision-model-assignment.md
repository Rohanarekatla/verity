# Vision tasks → models (Week 10 artifact, both tracks)

**Status: DRAFT by Track A, 19 Oct 2026 — Nikhil to confirm the model
column and B10.x specifics at the pair session.** Vision remains a flag-gated
experiment (ADR-0002); nothing here turns it on.

The rule this table exists to enforce: **the model localises, the maths
decides** (ADR-0003). Each row therefore says what the model is *never*
asked to do — and two rows have no model at all, because the deterministic
pipeline now does the job better than a model could.

| Task | SC | Who does it | Never asked to do |
|---|---|---|---|
| Image inventory (A10.1) | — | **No model.** `inventoryImages`: DOM + computed style | — |
| OCR triage (A10.3) | 1.4.5 | **No model.** `image_triage.py` rules, each with a recorded reason | Decide a finding; rules only skip work |
| Text-in-image detection (B10.2) | 1.4.5 | OCR model *(Track B to name: Florence-2 OCR task vs. Tesseract)* — on triaged candidates only, one crop per distinct image | Say whether text is "essential" or a logotype (triage + human); emit pass/fail |
| Region grounding (B10.1) | 1.1.1 / 1.4.5 | Florence-2 *(Track B; IoU to be measured)* | Supply coordinates that are trusted without a DOM box to check them against |
| Alt-text adequacy (B2.2, Week 11) | 1.1.1 | VLM under the alt-text rubric, constrained decoding, abstain allowed | Fail an image on its own: output is `ai_assisted` at most, never authoritative |
| Contrast region localisation (B2.4) | 1.4.3 | **No model any more.** Glyphs are found exactly by diffing renders with text hidden (sampling.ts, 18 Oct) | — (originally: "boxes only, never a ratio") |
| Focus-visible judgment (B2.3) | 2.4.7 | **No model any more.** Computed-style diff, confirmed by a pixel diff around the element (traverse.ts) | — |

## What changed since the plan was written

- **B2.4 and B2.3 no longer need a model.** Both were scoped as "model
  localises a region"; end-to-end hardening replaced them with exact
  measurements (glyph masks from render diffs; pixel diffs for focus rings)
  that are faster and checkable against ground truth (2,280 contrast cases,
  0 errors). This narrows vision to what genuinely needs it: reading text in
  raster images, and judging alt-text meaning.
- **OCR volume is bounded before any model loads** — see
  `docs/measurements/image-triage.md` for the measured cut on real sites.

## Open for the pair session

1. Model for B10.2 OCR, and whether one single-slot model (B10.3) can serve
   both OCR and grounding to stay inside the memory budget.
2. Whether alt-text adequacy should ever see images triage marked
   `decorative` (proposal: no — `alt=""` is the author's declaration; a wrong
   declaration is a 1.1.1 issue for a human, not a model).
