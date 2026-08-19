# Rohan — Week 2 action items (Track A)

Everything on your plate before the Sunday 23 Aug gate, in priority order.
Track B's code is finished and tested (76 passing); the remaining work is
yours or joint.

Technical detail on the Track B side lives in
[`../week2-track-b-handover.md`](../week2-track-b-handover.md). This file is
just the list.

---

## 1. Pull first — the Python schemas changed

Before you start anything, `git pull`. Four changes touch the boundary
between our tracks:

| Change | Why it affects you |
|---|---|
| `RenderArtifact.element_screenshots` is now `dict[str, ElementCapture]` | It said `dict[str, str]` — a plain filename string. Your `elements.ts` sends objects. A real render payload would not have parsed. Now it matches. |
| `BoundingBox` is `float`, not `int` | `getBoundingClientRect()` returns subpixels. Ints would have rejected `x: 12.5` outright. |
| `Finding` has a new required `rule_id` | Dedup was recovering the axe rule name by string-splitting `Finding.id`. |
| `AuditReport` has a new `latency` block | B2.5. Read it from the report, not a stopwatch. |

`verity-schema.json` has been regenerated to match.

**There is now a test — `test_render_artifact_accepts_track_a_element_captures`
— that parses a realistic render payload.** If you change the `ElementCapture`
interface in `elements.ts`, it fails. That's intentional: the two sides drifted
silently once already and nothing caught it. When it fails, update
`verity/models/schemas.py` to match and re-run `python export_schema.py`.

---

## 2. Run the model measurements — do this before wiring anything (B2.1)

`Qwen3-VL-8B-Instruct` Q4 via `mlx-vlm` on your Mac. Record into
[`../measurements/spike-a.md`](../measurements/spike-a.md):

- Cold load time (seconds)
- Inference speed (tokens/sec, during structured JSON output — not free text)
- Peak memory (GB)
- The actual chip and unified memory config

**Do this first.** If the model loads in 40 s and runs at 8 tok/s, the latency
gate fails no matter how good precision turns out to be, and Saturday's
conversation is a different one. It's an hour's work to find out.

---

## 3. Wire mlx-vlm into `VisionAgent`

Three stubs in `verity/agents/vision.py`. For each: pass the matching rubric
as the system prompt, constrain decoding to the matching schema.

| Method | System prompt | Constrain to |
|---|---|---|
| `evaluate_alt_text()` | `ALT_TEXT_RUBRIC` | `AltTextJudgment` |
| `evaluate_focus_visible()` | `FOCUS_VISIBLE_RUBRIC` | `FocusVisibleJudgment` |
| `localise_contrast_regions()` | `CONTRAST_LOCALISATION_RUBRIC` | `ContrastRegionLocalisation` |

### Two things that will invalidate the whole spike if you get them wrong

**Do not remove the `unknown` / `located` options from the schema you hand to
the decoder.** It is tempting — a model that always returns boxes is much
easier to parse, and the optional fields make the parsing branchy. But those
options *are the measurement*. Strip them and the model fabricates on 100% of
impossible cases, and Sunday's precision number means nothing. If parsing is
awkward, tell me and I'll change the schema shape — don't quietly simplify it
at the decoder.

**Boxes come back relative to the crop you supplied, not the page.** Map them
back through `box_css` and `device_pixel_ratio` from the `ElementCapture`. Do
not re-derive the scale factor — your own comment in `elements.ts` says why.

---

## 4. Run the corpus and record the results

Once the model is wired, run the A2.3 harness against it.

Note before you start: **focus-visible cannot be scored this week.** Nothing
captures a focused screenshot — that's A4.3 (Week 4) — and there's no
`outline_none` injector until B4.3 (Week 4). So the corpus covers alt-text
(`strip_alt`) and contrast localisation (`reduce_contrast`) only. Two of three
judgments. That's fine, but it needs to be stated in ADR-0002 rather than
noticed on Sunday night.

---

## 5. Write your half of the precision bar — before you run anything

[`../measurements/precision-bar.md`](../measurements/precision-bar.md) has my
proposal filled in and an empty section for yours.

The plan says propose **independently**, then agree one. Ideally write yours
without reading mine first — where we diverge is the useful signal. If you've
already read mine, say so in the doc and note what you'd have said otherwise.

This was due Monday. It's late. It needs to exist before results do, or it
isn't a bar.

---

## 6. Joint, Saturday 22 Aug

- **ADR-0002** — draft is at
  [`../adr/0002-vision-descope-decision.md`](../adr/0002-vision-descope-decision.md).
  Context is filled in; Decision and Consequences are blank pending the
  session. Both of us sign.
- **Sunday teach-back** — [`../teachback/2026-W02.md`](../teachback/2026-W02.md).
  My notes on your work are drafted. **You write the B → A half** — listener
  writes, per team-plan §2.3. Also: `2026-W01.md` was never written at all.

---

## 7. Small thing — CI doesn't run your corpus tests

`.github/workflows/ci.yml` runs `uv run pytest verity/tests/ -v`. That path
excludes `eval/tests/`, so `test_corpus_build.py` has never executed in CI.
One-line fix, but it's your test — your call.
