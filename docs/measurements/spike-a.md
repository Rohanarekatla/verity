# Spike A — Vision Model Measurements

Recorded on target hardware by `eval/vision/measure.py` (B2.1, B2.2).
Raw per-case output: `eval/vision/results.json`.

## Target hardware

- **Chip:** Apple M4 (10-core)
- **Memory:** 16 GB unified
- **Serving:** mlx-vlm 0.6.15, Metal

## Model actually run

**`mlx-community/Qwen2.5-VL-7B-Instruct-4bit`** — a 7B, 4-bit build.

> **Deviation from plan, stated openly.** The plan specifies
> Qwen3-VL-**8B**-Instruct-Q4. That build was not run here: this is the
> largest VL model that loads and runs comfortably on a base M4/16 GB
> today, and it stands in as a *directional* proxy. A 7B-4bit model is
> smaller and more quantised than the 8B target, so its numbers are a
> floor, not the ceiling. Re-run with the 8B build on a 32 GB machine
> before treating any of this as final.

## B2.1 — performance

| Metric | Value | Notes |
|---|---|---|
| Cold load (cached) | **3.6 s** | from local disk cache; first-ever download was ~8 min on an unauthenticated HF connection |
| Inference speed | **16.7 tok/s** | text generation, no image |
| Peak memory (MLX) | **5.4 GB** | model + KV cache; comfortable on 16 GB with headroom |
| Per-judgment latency | **5.0 s mean, 10.5 s max** | one image, structured-JSON judgment |

**16 GB is not the bottleneck.** The model fits with room to spare. The
cost is time: ~5 s per image judgment. A page with many images or many
axe-`incomplete` regions multiplies that, which is what the latency gate
(B2.5) has to weigh — but the memory fear from the research brief did not
materialise for a 7B build.

## B2.2 — alt-text meaningfulness precision

Eval set: 48 cases — 12 images with clear, nameable content
(`data/fixtures/vision-gallery.html`), each with one meaningful alt and
three placeholder alts (`IMG_4023.jpg`, `image`, `photo`). Placeholder
alts are ironclad negatives: a filename is not meaningful whatever the
image shows.

| Verdict | Count | |
|---|---|---|
| `yes` (meaningful) | 10 | on 10 of 12 genuinely-good alts — correct |
| `unknown` (abstain) | 38 | all 36 placeholders + 2 good alts |
| `no` (not meaningful) | **0** | — |

| Measure | Bar | Actual | Met? |
|---|---|---|---|
| Precision (point) | ≥ 0.95 | **n/a — zero findings** | — |
| Precision (95% CI lower) | ≥ 0.90 | **n/a** | — |
| Recall on placeholders | (secondary) | **0 / 36 = 0%** | ✗ |
| Abstention rate | (ceiling) | **79%** | ✗ |
| Per-page latency | soft/hard | ~5 s / image (page total not yet measured) | — |

**Gate: FAIL — but read the failure mode.** The model never produced a
false positive, because it never produced a *finding at all*: it did not
once answer `no`, even for a literal filename like `IMG_4023.jpg` whose
own reasoning it wrote as *"does not convey any information about the
image."* It abstained 79% of the time.

So the failure is **over-abstention, not fabrication** — the safe
direction. As configured, the 7B model is a correct-but-useless
detector for this task: it will not lie, and it will not catch anything.

### What this does and does not tell us

- It is a real signal on a small (n=48), controlled set with a stand-in
  model — directional, not the final word.
- It does **not** cleanly separate three possible causes, and the
  Saturday session should weigh them before descoping outright:
  1. **Rubric balance.** `ALT_TEXT_RUBRIC` deliberately spends most of
     its words on when to answer `unknown`. That is the right instinct
     for precision, but a 7B model may follow it so literally that it
     never commits to `no`. Rebalancing the rubric is *not* gaming the
     bar — but it must be done and then re-measured, not assumed.
  2. **Model size/quant.** 7B-4bit vs the specified 8B-Instruct. The 8B
     build may commit where the 7B abstains.
  3. **Task framing.** Placeholder detection is deterministic (filename
     regex, placeholder dictionary — A11.2, Week 11). The VLM may be the
     wrong tool for the *placeholder* half; its real value is the
     harder "present but subtly wrong" alt, which this eval set does not
     contain.

## Not measured this week (documented, not skipped)

- **B2.3 focus-visible** — needs focused-screenshot capture, which is
  A4.3 (Week 4). No focus pairs exist yet. Carries forward.
- **B2.4 contrast-region localisation** — the harness and backend
  support it; a labelled localisation set was not built this week.
- **End-to-end page latency (B2.5)** — per-judgment latency is measured
  above; whole-page total depends on how many judgments a page triggers.

## Bottom line for the Saturday gate

The bar is not met. The honest options — for the two engineers to decide
and record in ADR-0002 — are descope Vision to needs-review-only, retry
with the 8B build and/or a rebalanced rubric before deciding, or lean on
the deterministic placeholder heuristics (Week 11) for this specific
task and reserve the VLM for the judgments it is actually better at.
Nothing here supports keeping alt-meaningfulness as a *gating* vision
finding on current evidence.
