# Contrast adjudication — precision against ground truth

**Measured 2026-10-18/19** (Track A, end-to-end hardening) with
`eval/contrast_precision.py`. Every case is text over a CSS-image background,
so axe marks it `incomplete` and Verity's pixel adjudicator has to decide; the
true worst-case ratio and size class are known for each. The bar is **zero**
contradicted verdicts — a false fail costs trust, a false pass ships a barrier.

## Result

| Sampler | Cases | Decided | False fail | False pass |
|---|---|---|---|---|
| Colour-distance split (Week 3 → 18 Oct) | 120 | 114 | **8** | 0 |
| + glyph halo + edge inset | 360 | 329 (91%) | 0 | 0 — but see below |
| Diff method, while being hardened (14 seeds) | 1,680 | 1,680 | 0* | 0 |
| **Five-shot diff, final build** (seeds 71–73) | **360** | **360 (100%)** | **0** | **0** |

\* one intermediate build produced 6 false fails on pill buttons (seed 17);
the cause — corner rasterisation differences counted as glyphs — was fixed
by bounding glyphs to the text's own line boxes, and that seed re-run clean.

The middle row looked clean on the easy corpus and still failed real sites
(apple.com "Buy" links at 1.8:1 that read at 5.3:1), which is why the harder
corpus (pills on contrasting pages, thin 300-weight 12px text, fine
checkerboard images, underlines) exists.

## What was wrong, in the order it was found

1. **SVG text read with CSS `color`, not `fill`.** White SVG text was measured
   as black; with BC-A2 font sizes it became an authoritative *fail*.
2. **Anti-aliased glyph edges counted as background.** Blends like
   rgb(242,212,209) between white text and red sat >60 RGB units from the
   text colour, so worst-case landed on them (~1.4:1 on 5.4:1 text).
3. **Element edges rounded outward picked up the page colour** behind the box.
4. **Thin strokes are mostly blended pixels.** Colour distance cannot find the
   glyphs of 14px/400 text at all; the halo cannot fix what was never found.
5. **Neighbouring text counted as background** (a ticker's incoming line, the
   next table cell — stripe.com).
6. **Rounded-corner rasterisation differs between shots**, so pill corners
   were taken for glyphs and the page colour behind them for background.

## The method now (node-worker/static/sampling.ts)

Five shots of one fixed clip: as rendered; this element's text transparent
(the diff **is** its glyphs, restricted to its own text line boxes); every
text on the page transparent (what is behind the glyphs, read only directly
under them); that again, and the as-rendered shot again — if either repeat
disagrees, the page moved and the region is `ambiguous`, never measured.
Translucent text and text whose colour matches no glyph pixel are never
adjudicated.

## Not covered by this corpus

Real photographs (only synthetic two-colour images), video and canvas,
`mix-blend-mode`, text-shadow halos that aid legibility (we hide shadows; a
shadow that rescues low contrast is not credited — conservative direction).
