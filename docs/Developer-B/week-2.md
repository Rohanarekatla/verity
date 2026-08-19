# Week 2 (Track B) — what we built and how it flows

Week 2 · 17–23 Aug · **Spike A — can an 8B vision model make accessibility
judgments without inventing things?**

Week 1 built the pipe: URL in, `AuditReport` out, using axe-core only.
Week 2 does two things on top of that:

1. **Prepares the vision layer** — the schemas and rubrics a local vision
   model will be forced to answer through (B2.2, B2.3, B2.4).
2. **Makes the existing pipeline trustworthy enough to measure with**
   (B2.5, plus a set of correctness fixes found in review).

---

## Part 1 — The flow

### The main scan flow (what happens when you run the CLI)

```
[ USER IN TERMINAL ]
   uv run python -m verity.cli scan https://example.com -o report.json
        │
        ▼
1. verity/cli.py  (B1.4 — "The Front Door")
        │   - Reads the command, calls scan_url().
        ▼
2. verity/orchestrator/main.py  (B1.3 — "The Manager")
        │   - Starts a stopwatch (B2.5 — NEW).
        │   - Creates an RPCClient to talk to Node.
        ▼
3. verity/orchestrator/rpc_client.py  (B1.2 — "The Telephone")
        │   - Spawns Rohan's Node worker in the background.
        │   - Sends {"method": "render"} over stdio.
        ▼
[ NODE: opens Chromium, loads the page, waits for it to settle,
  saves DOM / screenshot / AX-tree, and NEW in W2: crops a PNG of
  every image-bearing element with its box in CSS *and* device pixels ]
        │
        │   replies: { artifactId, page_state: { content_hash }, ... }
        ▼
2. main.py
        │   - CHECK (NEW): no content_hash? Stop with an error.
        │     It used to quietly substitute "default_hash".
        │   - Records how long render took.
        │   - Sends {"method": "runAxe"} for the same artifactId.
        ▼
[ NODE: injects axe-core into that same page, returns TWO buckets ]
        │
        │   violations  → axe is SURE it's broken
        │   incomplete  → axe COULDN'T TELL (e.g. text on a background image)
        ▼
2. main.py  — turns raw axe JSON into strict Findings
        │
        ├── for each VIOLATION:
        │      - Does it carry a WCAG tag?  wcag143 → SC "1.4.3"
        │      - No tag (axe "best-practice" like `region`)? SKIP IT.
        │        Calling it a WCAG failure would be a false positive.
        │      - Build a Finding, provenance = AUTHORITATIVE
        │      - id = sha256(rule|selector)  ← NEW, was random per run
        │
        └── for each INCOMPLETE that is `color-contrast`:
               - Same WCAG-tag check (NEW — this guard was missing,
                 and without it one odd item killed the whole scan)
               - Build a Finding, then hand it to...
                     ▼
        4. verity/agents/contrast.py  ("could axe decide? no.")
               - provenance → NEEDS REVIEW
               - outcome    → cantTell
               - confidence → 0.0 / "axe-incomplete"   ← NEW
               - modality   → partial                  ← NEW
        ▼
5. verity/agents/validator/dedup.py  ("The Filter")
        │   - Same rule on the same element twice? Keep one.
        │   - Signature in waivers.yaml? Mark it waived.
        │   - NEW: waivers.yaml is found from the repo root, so this
        │     works no matter which folder you ran the CLI from.
        ▼
2. main.py — build_conformance_map()  (NEW function)
        │   - One verdict per success criterion, WORST WINS.
        │   - Waived findings are excluded.
        │   - Stops the stopwatch, fills in AuditReport.latency.
        ▼
6. verity/models/schemas.py  (B1.1 — "The Rulebook")
        │   - Validates the whole thing. If any field is wrong
        │     shape, it fails here rather than in the report.
        ▼
1. verity/cli.py
        │   - Prints the summary box.
        │   - Writes report.json.
        │   - Exit 1 ONLY if an AUTHORITATIVE fail exists and isn't waived.
        │     cantTell and AI-assisted findings never break your build.
```

### The vision flow (built this week, not yet connected)

```
[ Rohan's element crop:  el-abc123.png  +  box_css + box_device + dpr ]
        │
        ▼
verity/agents/vision.py  (B2.2 / B2.3 / B2.4)
        │
        │   system prompt = the RUBRIC   (tells the model when to say "I can't tell")
        │   output shape  = the SCHEMA   (constrained decoding — the model
        │                                 physically cannot return anything else)
        ▼
   ┌─────────────────────┬──────────────────────┬───────────────────────────┐
   │ AltTextJudgment     │ FocusVisibleJudgment │ ContrastRegionLocalisation│
   │ yes / no / unknown  │ yes / no / unknown   │ located: yes / unknown    │
   │ + reasoning         │ + reasoning          │ + 2 boxes (only if "yes") │
   └─────────────────────┴──────────────────────┴───────────────────────────┘
        │
        ▼
[ STUBBED — every method returns "unknown" until Rohan wires mlx-vlm ]
        │
        ▼
(Week 3) the contrast maths samples the pixels inside those boxes
         and decides pass/fail. The MODEL LOCATES. THE MATHS DECIDES.
```

---

## Part 2 — The files, and what each one does

### `verity/agents/vision.py` — NEW this week (B2.2, B2.3, B2.4)

**Who calls it:** nobody yet. Rohan wires the model in, then the Spike A
corpus harness calls it.

**What it does:** it defines the *only* answers a vision model is allowed to
give, and the instructions it's given before answering.

Two halves, and both matter:

- **The schema** controls the *shape* of the answer. With constrained
  decoding, the model literally cannot emit a field that isn't in the schema.
- **The rubric** is the system prompt. It controls the *honesty* of the
  answer — mostly by explaining, at length, when the right answer is
  "I can't tell".

**The problem it exists to solve — the fabrication trap:**

Imagine you show the model a crop of a plain blue button with no text on it,
and the schema *requires* a `foreground_text_bbox`. Constrained decoding means
the model cannot refuse. So it writes:

```json
{ "foreground_text_bbox": { "x": 12, "y": 8, "width": 60, "height": 14 } }
```

Perfectly formatted. Completely invented. Then Week 3's contrast maths samples
those pixels and produces a real-looking ratio for text that does not exist.

The fix is that every judgment has a legal way to decline:

```json
{ "located": "unknown" }
```

And if the model says `unknown` but supplies boxes anyway, Pydantic rejects it
— that combination can only mean it made them up.

**The one rule across all three:** the model never reports a contrast ratio, a
colour, or a pass/fail verdict. There is no field for it. It reports *where
things are*; the deterministic maths decides *whether they pass*.

### `verity/orchestrator/main.py` — extended (B2.5 + fixes)

**Who calls it:** `cli.py`.

**New this week:**

- **Latency in the report.** `AuditReport.latency` now carries
  `render_seconds`, `analysis_seconds`, `total_seconds`. Week 2 has a second,
  independent gate on speed — if a page takes 90 s, "runs in CI" is quietly
  false. That gate needs a number in the JSON, not a log line.
- **`derive_finding_id()`** — finding ids are now `sha256(rule|selector)`.
- **`build_conformance_map()`** — worst outcome wins per criterion.
- Two safety guards (see Part 3).

### `verity/models/schemas.py` — extended (B1.1)

**New:** `ElementCapture` (matching Rohan's TypeScript exactly), `Latency`,
`Finding.rule_id`, and `BoundingBox` widened from `int` to `float`.

### `verity/agents/contrast.py` and `validator/dedup.py`

These landed early — they're really B3.1 (Week 3), B6.1 (Week 6) and B7.1–B7.2
(Week 7). We agreed to keep them and fix the bugs rather than revert. Expiry
enforcement (B7.3) is deliberately still not implemented.

---

## Part 3 — The bugs found in review, in plain terms

Six real problems, all now fixed and covered by tests.

### 1. Finding IDs changed on every single run

`hash("#btn")` in Python is deliberately randomised per process. So scanning
the *same unchanged page* twice gave different ids:

```
run 1 → color-contrast-be95
run 2 → color-contrast-2be5
run 3 → color-contrast-49fb
```

Now sha256: `color-contrast-8e26424cbad4`, every time.

**Why it mattered:** Week 7 builds "what's new since last scan?". With
churning ids, *everything* looks new, every time.

### 2. A real failure could be hidden by an unsure one

A page with a **definite** contrast failure on `#buy-button` and an **unsure**
one on `#hero-text` — both are SC 1.4.3. The old code built the map with
"last one wins", and unsure items are always processed last:

```
Before:  "conformance": { "1.4.3": "cantTell" }   ← the real failure vanished
After:   "conformance": { "1.4.3": "fail" }
```

### 3. `cantTell` findings claimed to be 100% certain

Straight from the old `report.json` in this repo:

```json
"outcome": "cantTell",                                    ← "I don't know"
"confidence": { "score": 1.0, "method": "deterministic" } ← "100% certain"
```

Those contradict each other. Now `0.0 / "axe-incomplete"`, modality `partial`.

### 4. The Python and TypeScript sides disagreed

Rohan's worker sends an object per element:

```json
"#hero": { "selector": "#hero", "path": "el-abc.png",
           "box_css":    {"x": 12.5, "y": 40, "width": 300.25, "height": 150.5},
           "box_device": {"x": 25,   "y": 80, "width": 600.5,  "height": 301},
           "device_pixel_ratio": 2.0 }
```

Our schema said "just a filename string". It hadn't blown up only because
nothing validated it yet. There's now a test that parses a real payload, so
the two sides can't drift silently again.

### 5. Waivers silently stopped working from other folders

```
cd ~/verity  && verity scan ...   → waivers applied ✓
cd ~/Desktop && verity scan ...   → waivers ignored, no warning ✗
```

Also: the fingerprint sitting in `waivers.yaml` matched nothing the engine
could produce — brute-forced it to be sure. That waiver had never once
applied. The file is now empty with instructions for generating a real one.

### 6. One odd axe item could kill the entire scan

The `violations` loop checked "does this have a WCAG tag?" before mapping it.
The `incomplete` loop didn't. If axe ever retags `color-contrast`, the old
code raised and the whole scan died instead of skipping one node.

---

## Part 4 — Status

| Task | What | Status |
|---|---|---|
| B2.1 | Model measurements on target hardware | **Blocked** — needs the Mac; delegated to Rohan |
| B2.2 | Alt-text judge + rubric | Done |
| B2.3 | Focus-visible judge + rubric | Done (code) — **not measurable this week**, see below |
| B2.4 | Contrast localisation, box only | Done |
| B2.5 | End-to-end latency | Done |

**76 tests passing.** `verity-schema.json` regenerated.

**Known limitation for the gate:** focus-visible has no data to run against.
Nothing captures a focused screenshot — that's A4.3 (Week 4) — and there's no
`outline_none` injector until B4.3 (Week 4). So Sunday's precision number
covers **two of three** judgments. Recorded in ADR-0002 rather than left to be
discovered.

**Also worth knowing:** the corpus is 117 usable cases, not the ~200 the plan
assumed — which is why the proposed bar is stated as a confidence-interval
lower bound rather than a single number.

---

## Related documents

- [`../measurements/precision-bar.md`](../measurements/precision-bar.md) — the bar, proposed before results
- [`../measurements/spike-a.md`](../measurements/spike-a.md) — hardware measurements (Rohan to fill)
- [`../adr/0002-vision-descope-decision.md`](../adr/0002-vision-descope-decision.md) — the descope decision (Saturday)
- [`../week2-track-b-handover.md`](../week2-track-b-handover.md) — technical handover to Track A
- [`../Developer-A/week-2-action-items.md`](../Developer-A/week-2-action-items.md) — Rohan's list
- [`week-1.md`](week-1.md) — the Week 1 flow this builds on
