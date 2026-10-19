# End-to-end hardening — 18–19 Oct 2026

**Track A.** The first time Verity was tested as a *product* rather than as
units: a fresh clone, the real CLI on every fixture, a ground-truth contrast
corpus, the official APG examples, and ten real websites (example.com,
gov.uk, w3.org/WAI, Wikipedia, MDN, GitHub, BBC News, Apple, Hacker News,
Stripe). Every authoritative verdict that looked wrong was checked by hand —
screenshots, or driving the page directly — before anything was changed.

## Clean checkout (S5.3, open since Week 5)

`git clone` → `npm ci` → `npx playwright install chromium` → `uv sync` → all
suites green (Node 44, Python 366 at the start of this work). **S5.3 is done.**

## What was broken

Ordered by how badly it would have hurt a user.

| # | Area | Symptom | Cause | Fix |
|---|---|---|---|---|
| 1 | CLI | A crash exited **1** — CI reads that as "gating accessibility failures" | One exit code for two meanings | Exit **2** = scan could not complete; the Action says so instead of blaming the site |
| 2 | Render | **6 of 10 real sites could not be scanned** | CSP blocked the inline axe injection (gov.uk, MDN); `networkidle` never reached (GitHub, Stripe, Apple, BBC); every image screenshotted one by one (>120 s) | `bypassCSP`; load + bounded best-effort idle; crop budget (60 / 15 s); CLI default timeout 120 s |
| 3 | Contrast | Authoritative **false fails** — SVG text, anti-aliased edges, page colour at element edges, thin strokes, neighbour text, pill corners | The colour-distance glyph/background split (Week 3) | Rewritten sampler: glyphs found by diffing shots with text hidden; see `contrast-precision.md` (1,680/1,680 correct) |
| 4 | Contrast | BC-A2 (18 Oct) turned #3's undecided cases into authoritative fails | Font size made bad measurements decisive | Fixed by #3; plus "no glyph pixel matches the text colour" is never a verdict |
| 5 | Keyboard | A YouTube embed reported as a **keyboard trap**, plus 25 "unreachable" elements | Focus inside an iframe leaves the outer `activeElement` on the frame; a stopped traversal judged everything after it | Iframe presses are not repeats; a trapped run is `complete: false` |
| 6 | Keyboard | SC 2.4.3 needs-review on **every** real page | `tabindex: None` (attribute absent — a plain button) read as "not recorded" | None means absent, per the TabStop contract |
| 7 | Keyboard | SC 2.4.7 **false fail** on github.com's email field | Indicator drawn by a wrapper's `:focus-within`; only the element's own style was compared | A "no indicator" verdict is confirmed by pixels first |
| 8 | Contracts | `verity scan` ignored the Week 9 runner — a click-only `<div role="button">` exited 0 | Never wired into `scan_url` | Wired, after the traversal (it presses keys) |
| 9 | Contracts | Real-site false fails: accordions, all-tabbable tablists, `tabindex=-1` nav, async widgets | APG conformance treated as WCAG conformance; effects read two frames after the key | Keyboard **parity** with a click; APG-only deviations reported as warnings; wait for the step's effect (≤1.2 s) |
| 10 | CLI | `verity scan ./page.html` failed with "Cannot navigate to invalid URL" | Paths not accepted | Local files become `file://` URLs (files only) |
| 11 | Contrast | apple.com "Buy" links measured at 1.9:1 (really 7:1) | Restoring hidden text re-ran every `transition: all`, so the *next* element was captured mid-fade | Transitions frozen for the whole hide/restore cycle |
| 12 | Contrast | stripe.com number ticker failed at 2.9:1 (really 4.7:1) | Playwright's `animations: "disabled"` froze motion per shot, so the moving-page guard never fired | Real animation is captured; motion ⇒ ambiguous |
| 13 | Contrast | apple.com tile text failed at 1.05:1 (white on black) | `background-clip: text` paints glyphs with the background, not `color` | Paint-mismatch ⇒ ambiguous |
| 14 | Contrast | developer.mozilla.org decorative circle text failed | Text inside `aria-hidden="true"` is usually decoration (exempt) | A would-be fail there goes to review |
| 15 | Keyboard / contrast | github.com: the shots photographed the wrong place, or the sticky header, or an element still fading in | `scroll-behavior: smooth`; `block: "nearest"` parks elements under fixed bars; scroll-reveal animations | Instant, centred scroll; box re-measured; occlusion check; wait for full opacity — otherwise "could not measure" |
| 16 | Contracts | apple.com's bag button and gallery tabs "did nothing" | Effects are asynchronous (fetch, slide animation); the gallery also autoplays | Wait for the step's effect (≤1.2 s); a widget that changes on its own is not judged on key effects |
| 16b | Keyboard | stripe.com: a carousel "Previous" button reported unreachable (SC 2.1.1) | Disabled while Tab passed it, enabled by the time unreached elements were classified | Only controls focusable when the traversal began can be barriers |
| 16c | Contracts | apple.com gallery arrows "did nothing" | Selection flips at once, focus moves after the animation; the effect wait stopped at the first change | Steps declare what they expect (`expect: "focus"`) and the worker waits for that |
| 17 | Tests | Python suite hung for 20+ minutes on one machine | A vision test imported `mlx_vlm` (→ transformers) just to ask "is it installed?" | `importlib.util.find_spec` |

Also found on the test machine: three orphaned Node workers from a run on
17 Oct, each at 100% CPU for over a day. They predate this work (old code),
were stuck in a synchronous loop so SIGTERM never ran their handler, and were
killed. The current client escalates to SIGKILL after 3 s; an orchestrator
that is itself killed abruptly still leaves its worker to exit on stdin EOF.

## Real-site results after the fixes

All ten sites scan (2–235 s). Authoritative failures that remain from
Verity's own agents (keyboard, interaction, pixel contrast) were each checked:

- **github.com** — a `role="tablist"` with no tab marked `aria-selected`:
  genuine (selected state not exposed, SC 4.1.2).
- **Wikipedia** — the navbox "v·t·e" links, `#3366cc` on `#ccccff` at 14px
  (3.49:1): genuine.
- **stripe.com** — `#7d8ba4` at 16px/300 on white (3.41:1; 3.44 by hand):
  genuine. Customer-story buttons with no focus indicator: genuine
  (photographed focused and unfocused — identical).
- **apple.com** — the iPad "Buy" link, `#0066cc` on the light-blue tile at
  14px (3.87:1): genuine.
- **Hacker News** — grey `#828282` text on `#f6f6ef` (~3.6:1 at 10pt): genuine,
  from axe directly.
- gov.uk, w3.org/WAI, MDN, BBC News, example.com: zero authoritative
  failures from Verity's own agents.

## Benchmarks kept in the repo

- `eval/contrast_precision.py` — ground-truth contrast corpus (any seed).
- `eval/apg_reference_check.py` — the live W3C APG examples (0 failures).
- Fixtures added for each regression: `keyboard-iframe.html`,
  `keyboard-focus-within.html`, the SVG case in `vision-gallery.html`.

## Not done here

- Gating on *new* findings only (B7.4) — Week 8's remaining half.
- Findings anchored to real source lines (SARIF `startLine` is always 1).
- Shadow DOM and iframe contents are still blind spots (reported as such).
