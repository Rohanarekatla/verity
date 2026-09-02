# Rohan — Week 3 action items (Track A)

Week 3 · 31 Aug – 6 Sep · contrast-over-image adjudication.
▶ Gate Sun 6 Sep — **beat axe-core recall on contrast-over-image fixtures at
zero new false positives.**

Track B (B3.1–B3.4) is complete and all tests pass. Three things below are on
your side, and **item 1 currently blocks the gate**.

---

## 1. `contrast_over_image` isn't registered in the corpus — this blocks Sunday

I shipped the injector at `eval/inject/contrast_over_image.py` (B3.4). It puts
text over an inlined data-URI background image so axe-core cannot read the
background and marks the node `incomplete` — which is exactly the case the new
adjudicator exists to resolve.

But `eval/corpus/build.py` has a hardcoded injector registry, and it still
lists only `strip_alt`, `detach_label` and `reduce_contrast`. **So the corpus
generates zero contrast-over-image cases, and there is nothing to measure
"beats axe-core recall" against.**

That file is yours (A2.3), so I have not touched it. What it needs:

- add `contrast_over_image` to the `INJECTORS` list, with a target rule for
  which elements are valid subjects (text-bearing block elements — the same
  shape as `reduce_contrast`'s target rule should be close)
- add its entry to the `_ALLOWED_ATTRS` verification map:
  `"contrast_over_image": {"style", "data-verity-original-style-coi"}`

Note the marker attribute is deliberately **not** `data-verity-original-style`.
Both injectors write to `style`, and a shared marker would let one injector's
`revert` silently undo the other's — a corpus case that quietly lost its
defect, which is the worst possible failure in labelled data. There's a test
covering that (`test_contrast_over_image_uses_its_own_marker_attribute`).

## 2. `dist/` was stale and it cost an hour

`npm run build` had not been run since before Week 2. `dist/` was missing both
`crawler/elements.js` (A2.1) and `static/sampling.js` (A3.4), so the compiled
worker did not have `sampleRegion` even though the TypeScript did.

The symptom was two failures in `test_sampling.py` reading
`RuntimeError: unknown method: sampleRegion` — which looks like a Python bug
and isn't.

The skip guard is `WORKER_JS.exists()`, which only proves *a* build exists, not
a current one. Suggestion: check for `dist/static/sampling.js` specifically, or
compare mtimes against the `.ts` sources, so a stale build produces an honest
skip instead of a confusing failure. Your file, your call.

## 3. `RegionSample` has no reason code (not urgent — Week 4)

`sampled: bool` tells me sampling failed but not why. So "cross-origin canvas",
"video frame" and "element is animating" all collapse into one reason in the
report:

```
"contrast_adjudication": { "resolved": false, "reason": "sampling-failed" }
```

Correct, and safe — every one of them lands on `cantTell` / `NEEDS_REVIEW` and
none can gate a build. Just less useful to a user who has to go and find out
which it was. If you add something like
`reason: "cross_origin" | "video" | "animating" | "no_text"`, I'll surface it
verbatim. No rush; this doesn't affect the gate.

---

## What Track B built this week, so you know what you're integrating with

**B3.1 — `worst_case_ratio()`** in `verity/agents/contrast.py`. Takes the
foreground colour and the *set* of background samples your `sampleRegion`
returns, and computes the **minimum** ratio across them — not the average.
That's why A3.3 returning a per-region sample set rather than one averaged
colour matters: white text on a sky that darkens toward the horizon is
readable at the top and invisible at the bottom, and the average says it's
fine. Returns `None` on an empty set, which the caller treats as undecidable.

**B3.2 — `adjudicate_contrast()`**, wired into `scan_url()`. Each axe
`incomplete` colour-contrast node now triggers a `sampleRegion` call and gets
resolved from real pixels. **No model anywhere in this path** — it's WCAG
arithmetic over colours that were actually rendered.

**B3.3 — four inconclusive branches**, each recording a reason on the finding:
`sampling-failed`, `glyph-background-split-unreliable`, `no-background-samples`,
`text-size-unknown`. Your `ambiguous: true` flag maps to the second one and is
honoured exactly as your comment asks — such a region is never passed on the
deterministic path.

### The one design decision worth your review

`RegionSample` doesn't carry font size or weight, and `AxeNodeResult` doesn't
carry axe's check data either. WCAG 1.4.3 needs 4.5:1 for normal text but only
3:1 for large text (≥18pt, or 14pt bold). So the adjudicator only decides where
the answer is the same under **both** thresholds:

| worst ratio | outcome | provenance |
|---|---|---|
| ≥ 4.5 | pass | AUTHORITATIVE |
| < 3.0 | fail | AUTHORITATIVE |
| 3.0 – 4.5 | cantTell | NEEDS_REVIEW |

The middle band is a gap in the *input*, not in the maths. Assuming 4.5 there
would flag compliant large text as a failure — precisely the false positive
Sunday's gate forbids. There's a property test over all 256 greys asserting no
colour anywhere slips into a verdict it hasn't earned.

**If you'd rather widen that band**, the fix is on your side: add `fontSize`
and `fontWeight` to `AxeNodeResult` (axe's colour-contrast check already
computes them), and I'll apply the correct threshold per node and adjudicate
the 3.0–4.5 range too. Worth deciding together at the pair session — it's a
straight recall win, and it's the single biggest lever left on this gate.

---

## Joint, this week

- **Shared artifact:** implement relative luminance by hand from the WCAG spec
  text *before importing any library*. Mine is in `contrast.py`
  (`calculate_relative_luminance`) and is tested against the spec: black
  `0.0`, white `1.0`, black-on-white exactly `21.0`. Yours should be in
  TypeScript. **The two must agree to six decimal places** — that's the
  artifact, and the comparison is the point of it.
- **Pair (90 min):** walk axe-`incomplete` → authoritative together.
- **ADR-0003:** "the model localises, the math decides." Both sign.
- **Teach-back:** `docs/teachback/2026-W03.md`. Listener writes.
  (`2026-W01.md` is still missing.)

---

Previous week's list: [`week-2-action-items.md`](week-2-action-items.md).
