# Week 2 (Spike A) — Track B Handover to Track A

## What Developer B (Track B) Has Completed

### 1. Vision judgments — schemas *and* rubrics (`verity/agents/vision.py`)

Three judgments, each with a Pydantic schema for constrained decoding and a
rubric to use as the system prompt. The rubrics are the substantive half:
constrained decoding guarantees well-formed output, not true output, so each
rubric spends most of its words on when the answer is `unknown`.

| Judgment | Schema | Rubric |
|---|---|---|
| B2.2 alt-text meaningfulness | `AltTextJudgment` | `ALT_TEXT_RUBRIC` |
| B2.3 focus-visible, before/after | `FocusVisibleJudgment` | `FOCUS_VISIBLE_RUBRIC` |
| B2.4 contrast-region localisation | `ContrastRegionLocalisation` | `CONTRAST_LOCALISATION_RUBRIC` |

All three can abstain. `ContrastRegionLocalisation` now carries a `located`
field (`"yes"` / `"unknown"`) with both boxes optional and a validator tying
them together — `yes` requires both boxes, `unknown` forbids them. Without
it, constrained decoding forced a bounding box on every call including calls
where the crop contains no text, and the model had no legal way to decline.
There is still no field anywhere in which the model can report a contrast
ratio, a colour, or a verdict.

The stubs return the abstaining answer deliberately: until the model is
wired up every judgment is `unknown` and contributes nothing to the
precision measurement, which is the honest result.

### 2. End-to-end latency in the report (B2.5, `orchestrator/main.py`)

`AuditReport.latency` now carries `render_seconds`, `analysis_seconds` and
`total_seconds`, and survives JSON round-trip. It was previously a
`logger.info` line only, which default logging levels discard — Sunday's
latency gate needs a number in the report it can read. The phases are split
because the descope decision differs by culprit: a slow render is Week 17's
caching problem, slow analysis is not.

### 3. `element_screenshots` contract fixed (A2.2 boundary)

`RenderArtifact.element_screenshots` was typed `dict[str, str]` while
`node-worker/crawler/elements.ts` emits `Record<string, ElementCapture>`.
There is now a matching `ElementCapture` model (selector, path, `box_css`,
`box_device`, `device_pixel_ratio`), boxes are floats to preserve subpixels,
and `test_render_artifact_accepts_track_a_element_captures` parses a real
render payload so the two sides cannot drift again silently.

**Rohan — if you change `ElementCapture` in `elements.ts`, that test will
fail. Change `verity/models/schemas.py` to match and re-run
`python export_schema.py`.**

### 4. Measurements template (`docs/measurements/spike-a.md`)

Scaffolded for B2.1. Values are yours to fill in on target hardware.

---

## What Developer A (Track A) Needs to Do

Because Developer A operates on the target Apple Silicon hardware, Developer
A handles the actual execution of the `mlx-vlm` models.

### 1. Execute and record measurements (B2.1)

Run `Qwen3-VL-8B-Instruct` (Q4) via `mlx-vlm`. Record into
`docs/measurements/spike-a.md`: cold load time (s), inference speed
(tokens/sec), peak memory (GB), and the actual chip and memory configuration.

### 2. Wire `mlx-vlm` into `VisionAgent`

Three stubbed methods in `verity/agents/vision.py`. For each: pass the
matching `*_RUBRIC` as the system prompt, and constrain decoding to the
matching schema.

* `evaluate_alt_text()` → `ALT_TEXT_RUBRIC` → `AltTextJudgment`
* `evaluate_focus_visible()` → `FOCUS_VISIBLE_RUBRIC` → `FocusVisibleJudgment`
* `localise_contrast_regions()` → `CONTRAST_LOCALISATION_RUBRIC` → `ContrastRegionLocalisation`

Two things to watch:

* **Do not** drop the `unknown` / `located` options from the schema you hand
  to the constrained decoder to make parsing easier. They are the measurement.
* Boxes from `localise_contrast_regions()` are relative to **the crop you
  supplied**, not the page. Map them back through `box_css` /
  `device_pixel_ratio` from the `ElementCapture` — do not re-derive the scale.

### 3. Run the precision evaluation

Execute the Spike A corpus harness (A2.3) against the wired agents, then we
compare against Monday's precision bar and make the descope decision jointly
for ADR-0002.

---

## Corrections to the previous version of this handover

The earlier draft claimed the rubrics were done (they were not — only the
schemas existed), and claimed latency was tracked (it was logged, then
discarded). Both are now actually true. A code review also found and fixed:
non-reproducible finding ids built on `hash()`, a conformance map where an
undecided `cantTell` overwrote a proven `fail` on SC 1.4.3, a missing
success-criterion guard on the `incomplete` loop, a silent `"default_hash"`
placeholder for `page_state_hash`, and a cwd-relative waivers path.
