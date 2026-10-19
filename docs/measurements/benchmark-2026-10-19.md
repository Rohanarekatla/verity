# Verity vs axe-core, Lighthouse, Pa11y and IBM Equal Access

**Measured 2026-10-19** with `eval/benchmark/benchmark.py` (BC-C2 — "a
reproducible, honest benchmark"). Anyone can re-run it; the first run installs
the pinned competitor versions into a git-ignored folder.

| Tool | Version | Engine |
|---|---|---|
| Verity | main @ this commit | axe-core 4.13.0 + pixel / keyboard / contract agents |
| axe-core | 4.13.0 | — |
| Lighthouse | 12.8.2 | axe-core |
| Pa11y | 8.0.0 | HTML_CodeSniffer |
| IBM Equal Access | accessibility-checker 4.0.34 | IBM rules (WCAG 2.2 policy) |

## How it is kept fair

- Every tool scans the **same pages over HTTP** in the same Chromium.
- Every finding is resolved to the **DOM element it names** (CSS selector or
  XPath) before it is credited to a test case.
- Only findings on the **criterion under test** count. Contrast: each tool's
  own contrast rule. Keyboard: findings mapped to SC 2.1.1, 2.1.2, 2.4.3,
  2.4.7 or 4.1.2 — via axe's WCAG tags, Pa11y's codes, IBM's rule docs. A
  landmark best-practice rule firing near a keyboard trap is not "catching
  the trap"; a target-size finding on a clean widget is not a false alarm.
- "Sent to review" is reported separately from "caught": a review flag is
  honest, but a person still has to do the work.

## Contrast — truth is the WCAG worst-case ratio

Text over CSS images and gradients (the case axe marks `incomplete`), from
`eval/contrast_precision.py`, seeds 101–102, plus a solid-background control
set every tool should get right.

| Tool | Set | True fails | Caught | Sent to review | Missed silently | False fails |
|---|---|---|---|---|---|---|
| **Verity** | image / gradient | 202 | **202** | 0 | **0** | **0** |
| axe-core | image / gradient | 202 | 0 | 202 | 0 | 0 |
| Lighthouse | image / gradient | 202 | 0 | 0 | **202** | 0 |
| Pa11y | image / gradient | 202 | 0 | 202 | 0 | 0 |
| IBM | image / gradient | 202 | 0 | 168 | 34 | 0 |
| all five | solid (control) | 43 | 43 each | 0 | 0 | 0 |

- **Lighthouse reports nothing** for text over a background image — a page
  with 202 failing text regions scores as if they were fine.
- axe and Pa11y are honest ("needs review") but leave all 202 to a human.
- IBM sends most to review and silently misses 34.
- On solid backgrounds everyone is right — Verity's lead is exactly the half
  the others cannot decide, and it gave up no precision to get it.

## Keyboard & widgets — one known defect per page, plus clean twins

Defects: keyboard trap, unreachable control, positive tabindex, no focus
indicator, click-only `div role="button"`, menu button that strands focus,
tabs unreachable without arrow keys. Clean: APG-correct disclosure / menu
button / tablists, an iframe embed, a `:focus-within` focus ring.

| Tool | Defects caught | Sent to review | False alarms on clean widgets |
|---|---|---|---|
| **Verity** | **7 / 7** | 0 | **0 / 8** |
| axe-core | 0 / 7 | 1 | 0 / 8 |
| Lighthouse | 0 / 7 | 0 | 0 / 8 |
| Pa11y | 0 / 7 | 0 | 0 / 8 |
| IBM | 0 / 7 | 3 | 0 / 8 |

None of the others operates the page with a keyboard. (axe and Lighthouse do
flag positive `tabindex` — as a best-practice rule, not a WCAG failure, so it
does not count here.)

## Speed — where Verity loses

| Tool | All 15 pages | 120-case corpus page | Small widget page |
|---|---|---|---|
| Verity, before profiling | 241 s | 92 s | 3.0 s |
| **Verity, now** | **109 s** | **26 s** | **3.0 s** |
| axe-core | 1.8 s | 0.2 s | 0.1 s |
| Lighthouse | 150 s | 11 s | 9.9 s |
| Pa11y | 33 s | 2.4 s | 2.2 s |
| IBM | 29 s | 3.5 s | 1.8 s |

Verity is now faster than Lighthouse overall, but still an order of
magnitude slower than axe alone — and it should be: it does far more per page (five screenshots per contrast region, a full
Tab traversal with pixel-confirmed focus indicators, key-driven contract
checks). Profiling found the contrast sampler spent 85% of its time shipping
pixel arrays out of the page as JSON; decoding PNGs in Node and dropping
needless frame waits took it from 700 ms to 165 ms per region with identical
results.

## Limits of this benchmark

- Synthetic pages with known answers: it measures correctness on exactly the
  cases it contains, not coverage of WCAG as a whole. axe-core's broad rule
  set is inside Verity, so everything axe finds Verity finds too.
- Seven keyboard defects is a small set; it shows a capability gap, not a
  rate. Real-site results are in `e2e-hardening-2026-10-18.md`.
- Lighthouse and IBM were run with their defaults for accessibility; other
  configurations could change their review/miss split, not their decisions.
