# Image triage (A10.3) — how much OCR it removes, on real pages

**Measured 2026-10-19** (Track A, Week 10): render → `inventoryImages`
(A10.1) → `image_triage.triage` (A10.3) → `captureImages` of one crop per
distinct candidate into the content-addressed store (A10.2).

| Site | Images | Not rendered | OCR candidates | Distinct | Crop files | Triage + capture |
|---|---|---|---|---|---|---|
| gov.uk | 17 | 2 | 0 | 0 | 0 | 0.0 s |
| w3.org/WAI | 15 | 1 | 0 | 0 | 0 | 0.0 s |
| Wikipedia article | 186 | 1 | 2 | 2 | 2 | 0.2 s |
| MDN | 6 | 0 | 0 | 0 | 0 | 0.0 s |
| github.com | 146 | 72 | 6 | 6 | 6 | 1.4 s |
| BBC News | 61 | 12 | 26 | 23 | 18 | 2.0 s |
| apple.com | 144 | 85 | 9 | 5 | 5 | 0.5 s |
| stripe.com | 227 | 58 | 4 | 4 | 4 | 0.9 s |
| **Total** | **802** | **231** | **47** | **40** | **35** | |

**93% of rendered images never reach OCR** (571 → 40 distinct). What remains
is the right set: news photographs (BBC), product and campaign images
(Apple, GitHub), a `<canvas>`, and Wikipedia's "Powered by MediaWiki" badges
— which genuinely are images of text.

## Why each image was skipped (every result carries its reason)

| Category | Count | Rule |
|---|---|---|
| hidden | 231 | not rendered (carousels' off-screen slides, mobile-only duplicates) |
| not-text | 234 | inline SVG (vector text is real text), or a CSS background behind real HTML text — mostly Wikipedia's icon-sprite links |
| tiny | 152 | under 24×12 px — no readable text fits |
| decorative | 115 | `alt=""`, `role=presentation/none`, or inside `aria-hidden` — the author's declaration |
| logo | 15 | named a logo (`alt="Stripe logo"`, `class="…logo…"`) or the header's home link — logotypes are exempt from 1.4.5 |
| icon | 8 | ≤ 48 px, square-ish, in a control or landmark |

## One rule corrected while measuring

The first version treated any alt text *containing* "logo" as a logo, and
skipped apple.com's *"Apple Card, front, Apple logo in top left…"* and a
stripe.com street photograph. An alt that **names** the image as a logo
("Stripe logo") is a logo; one that **describes a scene** containing one is a
content image. Fixed and pinned by tests.

## Two levels of de-duplication (A10.2)

1. **Before capture** — triage groups candidates by source + rendered size
   and crops one per group. This is what cuts volume: the same photo shown at
   two fractional positions anti-aliases its edges differently, so its crops
   are *not* byte-identical.
2. **At storage** — crops are named by the sha256 of their bytes and never
   rewritten, so byte-identical crops (the common case for icons, and the same
   image across pages) are one file.

## The trade-off, stated

Triage only ever skips work, so a wrong skip costs **recall** on SC 1.4.5
(an image of text never OCR'd), never a false finding. The one rule that
*prevents* a false finding is `not-text` for a background behind real HTML
text: its crop contains that HTML text, and OCR would "find" it.
