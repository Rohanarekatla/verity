# Week 3 (Track B) — contrast-over-image adjudication

Week 3 · 31 Aug – 6 Sep
▶ Gate Sun 6 Sep — **beat axe-core's recall on contrast-over-image fixtures
at zero new false positives.**

---

## Part 1 — The problem, in one page

axe-core gives three answers, not two:

```
   ┌──────────────┐
   │   axe-core   │
   └──────┬───────┘
          │
   ┌──────┼──────────────────┐
   │      │                  │
   ▼      ▼                  ▼
 passes  violations      incomplete
 "fine"  "definitely     "I don't know"
          broken"              ▲
                               │
                    ───────────┴───────────
                     Week 3 lives here
```

The most common reason for `incomplete` is **text sitting on a background
image.** axe can read the text colour out of the CSS. It cannot read the
background, because the background is a photograph. So it declines to judge.

Until this week we passed that shrug straight through to the user:

```
Before Week 3:
   axe says "I don't know"  →  report says "needs review"  →  user opens
                                                              a colour picker
```

**Week 3's job: do the thing axe refused to do — and do it well enough that
the answer counts as authoritative.**

The catch is in the gate. It is not enough to answer *more* questions.
Every answer we give has to be right, and anything we are unsure about has
to stay "I don't know." One false positive and the gate fails.

---

## Part 2 — The four tasks

| # | Task | In plain terms |
|---|---|---|
| **B3.1** | Worst-case ratio | Given the text colour and a set of background colours, work out the contrast |
| **B3.2** | Adjudication pipeline | Take axe's "I don't know" pile and actually decide |
| **B3.3** | Inconclusive handling | Know when *not* to decide, and say so honestly |
| **B3.4** | `contrast_over_image` injector | Deliberately break test pages this way, so there is data to measure against |

Rohan's half (A3.1–A3.4) was already done when this started: his
`sampleRegion` reads the real pixels off the rendered page and hands them
back over RPC.

---

## Part 3 — B3.1: worst case, not average

`sampleRegion` returns a **list** of background colours, because the
background behind a piece of text is usually not one colour.

Picture white text over a photo of a sky:

```
   ┌────────────────────────────────────┐
   │  ███████ dark navy ███████         │   ← text here: perfectly readable
   │  ▓▓▓▓▓▓▓ mid blue  ▓▓▓▓▓▓▓         │
   │  ░░░░░░░ pale grey ░░░░░░░         │   ← text here: invisible
   └────────────────────────────────────┘

   background_samples: [ navy (21:1),  pale grey (1.1:1) ]

   average approach  →  mid blue  →  ~5:1   →  "looks fine"   ✗ WRONG
   worst-case        →  pale grey →   1.1:1 →  "unreadable"   ✓ RIGHT
```

A reader has to read **every** word, not the average word. So we take the
**minimum** ratio across all samples. That is the entire function.

This is also *why* Rohan's A3.3 returns a sample **set** rather than one
averaged colour — averaging produces a colour that appears nowhere on the
screen and a ratio no human ever experiences.

One detail: if the list is empty, `worst_case_ratio()` returns `None` —
not `0` (which would read as a failure) and not `21` (which would read as a
pass). Nothing is nothing.

---

## Part 4 — B3.2 and B3.3: deciding, and refusing to decide

### The flow for one `incomplete` node

```
  axe marks "#hero" incomplete
            │
            ▼
  ask Node worker:  sampleRegion(artifactId, "#hero")
            │
            ▼
  ┌─────────────────────────────────────────┐
  │  Did the call work at all?              │
  └────────────┬───────────────┬────────────┘
               │ no            │ yes
               ▼               ▼
       cantTell          ┌──────────────────────────────┐
     NEEDS_REVIEW        │ sampled == false?            │──yes──▶ cantTell
   "old worker,          └────────────┬─────────────────┘         reason:
    timeout, or                       │ no                        sampling-failed
    bad selector"                     ▼
                         ┌──────────────────────────────┐
                         │ ambiguous == true?           │──yes──▶ cantTell
                         │ (text/background pixels      │         reason:
                         │  couldn't be separated)      │         glyph-split
                         └────────────┬─────────────────┘
                                      │ no
                                      ▼
                         ┌──────────────────────────────┐
                         │ any background samples?      │──no───▶ cantTell
                         └────────────┬─────────────────┘         reason:
                                      │ yes                       no-background
                                      ▼
                            worst_case_ratio()
                                      │
                    ┌─────────────────┼──────────────────┐
                    │                 │                  │
              ratio >= 4.5      3.0 <= r < 4.5      ratio < 3.0
                    │                 │                  │
                    ▼                 ▼                  ▼
                 PASS             cantTell             FAIL
            AUTHORITATIVE      NEEDS_REVIEW      AUTHORITATIVE
                              reason:
                              text-size-unknown
```

**No AI model appears anywhere in this diagram.** It is arithmetic from the
WCAG spec over pixels that really exist on screen. That is precisely why the
result is allowed to be `AUTHORITATIVE` and gate a build — a model's opinion
never could be.

### Why there is a middle band

This is the part that protects the gate, and it is worth understanding.

WCAG SC 1.4.3 has **two** thresholds, not one:

| Text | Needs |
|---|---|
| Normal text | **4.5 : 1** |
| Large text (18pt+, or 14pt bold) | **3 : 1** |

Nobody in our pipeline knows the font size. Rohan's `RegionSample` doesn't
carry it, and axe's own check data doesn't reach us either.

So imagine a heading measured at **3.7 : 1**:

```
   if it's a large heading   →  3.7 >= 3.0  →  PASSES
   if it's normal body text  →  3.7 <  4.5  →  FAILS
```

Same number. Opposite verdicts.

If we had simply assumed 4.5:1 for everything, that compliant heading would
be reported as broken — **a false positive, which fails Sunday's gate on its
own.**

So the adjudicator only decides where **both** thresholds agree:

```
        3.0                4.5
   ──────┼──────────────────┼──────────▶  ratio
    FAIL │    cantTell      │   PASS
         │  "depends on     │
         │   text size"     │
```

We still **report the number** in the middle band, so a reviewer with the
page open finishes the job in about ten seconds:

> *"Contrast is 3.69:1. This passes SC 1.4.3 for large text (≥ 3:1) but
> fails for normal text (≥ 4.5:1), and the rendered text size is not
> available. Needs review."*

That band is a gap in the **input**, not in the maths. If Rohan adds
`fontSize`/`fontWeight`, the band closes and recall goes up. That is the
biggest remaining lever on this gate.

---

## Part 5 — B3.4: making the test data

To prove "we beat axe", you need pages where axe actually gives up.

`eval/inject/contrast_over_image.py` creates them. It takes a clean page and
drops a tiny background image behind an element's text:

```
BEFORE:   <p id="hero">Welcome</p>
                    │
                    ▼  inject()
AFTER:    <p id="hero"
             style="background-image: url('data:image/png;base64,...');
                    background-size: cover;
                    color: #7a7a7a;"
             data-verity-original-style-coi="VERITY_NO_STYLE">Welcome</p>
                    │
                    ▼  revert()
BACK TO:  <p id="hero">Welcome</p>       ← exactly as it started
```

The image is inlined as a **data URI**, so there is no network fetch, no
cross-origin problem, and the fixture stays a single self-contained file.

**One subtle thing worth knowing.** `reduce_contrast` (from Week 1) also
writes to the `style` attribute, and it remembers the original in
`data-verity-original-style`. This injector deliberately uses a *different*
marker, `data-verity-original-style-coi`.

If they shared a marker, running one injector's `revert` would silently undo
the other's — producing a corpus case that quietly lost its defect. In
labelled test data that is the worst possible bug, because nothing looks
wrong; the case just stops testing anything. There is a test for it.

---

## Part 6 — What changed in the report

Same page, same node, before and after this week:

```
BEFORE (Week 2)                      AFTER (Week 3)
──────────────────────────────────   ──────────────────────────────────
"outcome":    "cantTell"             "outcome":    "fail"
"provenance": "needs review"         "provenance": "authoritative"
"confidence": 0.0                    "confidence": 1.0
              "axe-incomplete"                     "wcag-contrast-arithmetic"
"message":    "Ensure the contrast   "message":    "Contrast 1.14:1 fails
               ... meets thresholds"                SC 1.4.3 at its worst
                                                    sampled background
                                                    region, for text of
                                                    any size."

                                     "contrast_adjudication": {
                                        "resolved": true,
                                        "worst_case_ratio": 1.1396,
                                        "foreground_rgb": [255,255,255],
                                        "background_samples_considered": 4,
                                        "text_pixel_count": 512,
                                        "verdict_basis":
                                          "below the 3:1 large-text threshold"
                                     }

exit code: 0  (never gated)          exit code: 1  (real failure, gates CI)
```

---

## Part 7 — Files

| File | What happened |
|---|---|
| `verity/agents/contrast.py` | Rewritten. `worst_case_ratio`, `adjudicate_contrast`, four refusal branches |
| `verity/orchestrator/main.py` | Added `_adjudicate_incomplete_contrast`, wired into `scan_url()` |
| `eval/inject/contrast_over_image.py` | New (B3.4) |
| `verity/tests/test_adjudication.py` | New — 14 tests |
| `verity/tests/test_injectors.py` | Added 5 injector tests |
| `verity/tests/test_main.py` | Added 3 pipeline tests |

**119 tests passing.** No Track A files were touched.

Notable test: a **property test over all 256 greys** on white, asserting that
no colour anywhere in the space slips into a verdict it hasn't earned.

---

## Part 8 — Status

**Done:** B3.1, B3.2, B3.3, B3.4.

**Blocked, and it's Rohan's:** `contrast_over_image` isn't registered in
`eval/corpus/build.py`, so the corpus generates **zero** cases of the type
Sunday's gate measures. Written up in
[`../Developer-A/week-3-action-items.md`](../Developer-A/week-3-action-items.md).

**Still joint this week:** the hand-written relative-luminance artifact (ours
is done and tested — black `0.0`, white `1.0`, black-on-white exactly
`21.0`; Rohan's TypeScript version must match to six decimals), the 90-minute
pair session, **ADR-0003**, and `docs/teachback/2026-W03.md`.

---

# Part 9 — The whole picture: Week 1 → Week 3

## What each week added

```
WEEK 1  ·  10–16 Aug  ·  "Make the pipe work"
├─ Python talks to a real browser over JSON-RPC
├─ axe-core runs, findings come back as strict typed objects
└─ CLI exits non-zero on real failures
        ▼
WEEK 2  ·  17–23 Aug  ·  "Can a vision model be trusted?"
├─ Three vision judgments, each able to say "I don't know"
├─ Latency measured and recorded
└─ ANSWER: not yet — the 7B model abstained on 79% of cases
        ▼
WEEK 3  ·  31 Aug – 6 Sep  ·  "Resolve what axe won't judge"
├─ Read the real pixels behind the text
├─ Worst-case WCAG maths, no model involved
└─ "I don't know" becomes an authoritative pass or fail
```

## The full scan, end to end, as it stands today

```
[ USER ]  uv run python -m verity.cli scan https://example.com -o report.json
     │
     ▼
┌────────────────────────────────────────────────────────────┐
│ cli.py                                    (W1 · B1.4)      │
│   reads the command, calls scan_url()                      │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ orchestrator/main.py                      (W1 · B1.3)      │
│   starts the stopwatch                    (W2 · B2.5)      │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ orchestrator/rpc_client.py                (W1 · B1.2)      │
│   spawns Rohan's Node worker, talks JSON-RPC over stdio    │
└────────────────────────┬───────────────────────────────────┘
                         ▼
        ╔════════════════════════════════════════════════════╗
        ║  NODE WORKER  (Track A — Rohan)                    ║
        ║                                                    ║
        ║  render()      W1 · A1.2   open Chromium, settle   ║
        ║                W2 · A2.1   crop every image        ║
        ║                            + box in CSS px         ║
        ║                            + box in device px      ║
        ║                                                    ║
        ║  runAxe()      W1 · A1.4   axe-core, 4 buckets     ║
        ║                W2 · A2.2   crop incomplete nodes   ║
        ║                                                    ║
        ║  sampleRegion() W3 · A3.4  read the REAL pixels:   ║
        ║                            text colour,            ║
        ║                            background sample set,  ║
        ║                            ambiguous? sampled?     ║
        ╚════════════════════════┬═══════════════════════════╝
                                 ▼
┌────────────────────────────────────────────────────────────┐
│ main.py — sort what came back                              │
│                                                            │
│   violations ──────────────────────────────┐               │
│     wcag143 → SC "1.4.3"                   │               │
│     no WCAG tag → dropped (not a failure)  │               │
│                                            │               │
│   incomplete (color-contrast) ─────┐       │               │
│                                    ▼       │               │
│              ┌──────────────────────────┐  │               │
│              │ agents/contrast.py       │  │               │
│              │        (W3 · B3.1-B3.3)  │  │               │
│              │                          │  │               │
│              │  sampleRegion → pixels   │  │               │
│              │  worst-case ratio        │  │               │
│              │  >=4.5 pass  <3.0 fail   │  │               │
│              │  between → cantTell      │  │               │
│              │  NO MODEL IN THIS PATH   │  │               │
│              └────────────┬─────────────┘  │               │
│                           │                │               │
│                           ▼                ▼               │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ agents/validator/dedup.py                 (early W6/W7)    │
│   same defect twice → keep one                             │
│   signature in waivers.yaml → mark waived                  │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ build_conformance_map()                                    │
│   one verdict per criterion, WORST WINS                    │
│   waived findings excluded                                 │
│   stopwatch stops → AuditReport.latency                    │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ models/schemas.py                         (W1 · B1.1)      │
│   validates the whole report before it leaves              │
└────────────────────────┬───────────────────────────────────┘
                         ▼
┌────────────────────────────────────────────────────────────┐
│ cli.py                                                     │
│   prints summary · writes report.json                      │
│   exit 1 ONLY on an authoritative, unwaived "fail"         │
└────────────────────────────────────────────────────────────┘


  SIDE-CAR (not in the scan — used to test the scanner)

  eval/inject/     strip_alt         W1 · B1.5
                   detach_label      W1 · B1.5
                   reduce_contrast   W1 · B1.5
                   contrast_over_image  W3 · B3.4   ← NEW

  eval/corpus/     30 clean pages × injectors = labelled cases
                                     W2 · A2.3
```

## The one idea running through all three weeks

Every week has added a different way for the system to say **"I don't
know"** — and made that the safe answer.

```
Week 1   a rule with no WCAG tag is DROPPED,
         not reported as a conformance failure

Week 2   every vision judgment can answer `unknown`,
         and the schema rejects a fabricated box

Week 3   four separate refusal branches, plus an entire
         ratio band left undecided because the font size
         is unknown
```

A finding that is wrong is worse than a finding that is missing. A missed
issue leaves the user exactly where they were. A false one costs them time,
then trust, then the tool. Everything above is a variation on that single
trade.

---

## Related documents

- [`week-1.md`](week-1.md) · [`week-2.md`](week-2.md)
- [`../Developer-A/week-3-action-items.md`](../Developer-A/week-3-action-items.md) — what's on Rohan's plate
- [`../execution-plan.md`](../execution-plan.md) — the 20-week schedule
