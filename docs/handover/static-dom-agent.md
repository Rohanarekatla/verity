# Handover — Static / DOM Agent (Rohan → Nikhil)

**Rotation #1 (S5.5).** From Phase 2, Nikhil owns the Static/DOM Agent and I
step back from it. The plan expects the new owner to push a non-trivial commit
to it, so this note exists to make that possible without archaeology. Rotation
is a bus-factor measure: if only one of us can touch a component, the project
has a single point of failure, and this is the component I wrote most of.

This is the deterministic half of the engine — render a page, run axe, sample
contrast pixels. **No model touches any of it** (ADR-0003), which is exactly
why it can gate a build.

---

## What it is

The Static/DOM Agent is the Node worker's capture-and-measure surface. It lives
behind the JSON-RPC methods `render`, `runAxe`, `sampleRegion` and
`releaseArtifact` (plus `traverseTabOrder`, which is the Interaction Agent and
is handled separately — it shares the page lifecycle but not the doctrine).

| Concern | File | Task |
|---|---|---|
| Browser lifecycle, render + settle + cache | `node-worker/crawler/render.ts` | A1.2/A1.3 |
| Live-page registry (peek/take/release) | `node-worker/crawler/pages.ts` | A3.x |
| axe-core injection + four buckets | `node-worker/static/axe.ts` | A1.4 |
| Element capture (crops, CSS+device boxes) | `node-worker/crawler/elements.ts` | A2.1/A2.2 |
| Contrast pixel sampling | `node-worker/static/sampling.ts` | A3.1–A3.3 |
| RPC wiring | `node-worker/rpc/handlers.ts` | — |

Python side it is consumed by `verity/orchestrator/main.py` (the pipeline) and
`verity/agents/contrast.py` (the adjudicator). Tests:
`node-worker/test/{render-axe,elements,sampling}.test.mjs` and
`verity/tests/test_sampling.py`.

---

## The invariants that are not obvious (break these and it fails silently)

1. **The page outlives a single call.** `render` keeps the Chromium page open,
   keyed by `artifactId`; `runAxe` and `sampleRegion` *peek* it (use without
   consuming) so the pixels sampled for contrast are the exact pixels axe
   judged. The orchestrator must `releaseArtifact` in a `finally`, and
   `closeAllPages()` sweeps leaks at shutdown. If you make `runAxe` close the
   page again, contrast sampling breaks on every real page and the tests that
   catch it are the lifecycle ones in `sampling.test.mjs`.

2. **Two coordinate systems, always both.** `elements.ts` stores every box in
   CSS pixels *and* device pixels with the `device_pixel_ratio` between them.
   The vision crop reasons in device pixels; the contrast maths maps back to a
   CSS selector. Store one and multiply later and the consumer that forgets is
   off by the DPR (2× on Retina).

3. **The cache key is content-addressed.** `.verity/cache/<sha256>/` where the
   sha is over the rendered content, not the URL — so two URLs that render
   identically share a cache entry and a re-render of unchanged content is
   stable across runs. (This was a W02 thin spot: the key is derived in
   `render.ts`; the stability test is `the cache key is content-addressed and
   stable across renders` in `render-axe.test.mjs`.)

4. **`captureElements` is sequential on purpose.** Concurrent element
   screenshots contend on the same page and produce flaky/torn crops. The
   comment says so; the slowness is deliberate and is Week 17's problem, not a
   bug to "fix" by parallelising.

---

## The two thin spots you flagged in teach-back — answered

From `docs/teachback/2026-W02.md` and `-W03.md`:

- **How glyph-region estimation decides which pixels are text.** It is not
  edge detection. `sampling.ts` reads the element's *computed foreground
  colour* from CSS, then classifies each pixel by Euclidean distance in RGB to
  that colour: within `TEXT_DISTANCE` (60) → "text", else → "background". Text
  is expected to be a thin minority of the element's area; when the "text"
  class outnumbers the background class, the split is untrustworthy (a
  background patch near the foreground colour got swallowed), and that is what
  sets `ambiguous`. So `ambiguous` is a statement about the *classifier's*
  confidence, not the contrast.

- **Why the top background sample is exact (`#808080` → 128,128,128) despite
  antialiasing.** Because we sample a *solid* region away from glyph edges.
  Antialiasing smears the boundary between text and background into
  intermediate colours, but the interior of a solid background fill is
  untouched, and it is the most *common* colour, so it sits at the top of the
  count-sorted sample set. The smeared edge colours are real samples too, but
  they are long-tail entries, not the mode. On a gradient there is no single
  mode and that is the whole reason `worst_case_ratio` takes the set, not an
  average.

---

## Where I'd start if I were you

- The first good non-trivial commit is the one ADR-0003 defers: add `fontSize`
  and `fontWeight` to `sampleRegion`'s output (the browser already computes
  them) so the contrast adjudicator can apply the correct 3.0 vs 4.5 threshold
  and resolve the band it currently leaves `cantTell`. It is self-contained,
  it is a real recall win, and it touches exactly this component.

## What I still own (not in this handover)

The Interaction Agent (`node-worker/interaction/traverse.ts`, A4.x) is new this
week and stays with me through Phase 2 — it is not part of this rotation. Its
page lifecycle is shared with the Static/DOM Agent, so a change to
`pages.ts` affects both; ping me before you change the registry semantics.
