# Week 2 (Spike A) — Track B Handover to Track A

## What Developer B (Track B) Has Completed
For Week 2 (Spike A), Developer B has completed the structural and pipeline requirements for the vision model evaluation.

1. **Vision Agent Schemas (`verity/agents/vision.py`)**
   We have defined the strict Pydantic schemas that the Vision Language Model (VLM) must conform to. These schemas prevent the "fabrication trap":
   * `AltTextJudgment`: Forces the model to evaluate alt-text meaning, with a mandatory `unknown` choice.
   * `FocusVisibleJudgment`: Evaluates focus outlines between before/after states.
   * `ContrastRegionLocalisation`: Forces the model to *only* return a bounding box (`VisionBoundingBox`) for text and background regions, ensuring the model never attempts to do contrast math itself.

2. **Latency Tracking Pipeline (`verity/orchestrator/main.py`)**
   We added an end-to-end latency tracker in the `scan_url()` pipeline. This captures the total time from the initial Node worker dispatch until the final findings are mapped, which is required to measure against our Week 2 latency bar.

3. **Measurements Template (`docs/measurements/spike-a.md`)**
   We scaffolded the markdown template required for Task B2.1 to record cold load times, inference speed, and peak memory usage.

---

## What Developer A (Track A) Needs to Do

Because Developer A operates on the target Apple Silicon hardware (Mac), Developer A must handle the actual execution of the `mlx-vlm` models.

### 1. Execute and Record Measurements (Task B2.1)
Run `Qwen3-VL-8B-Instruct` (Q4 quantization) via `mlx-vlm` on your Mac. Record the following metrics into `docs/measurements/spike-a.md`:
* Cold load time (seconds)
* Inference speed (tokens/sec)
* Peak memory usage (GB)

### 2. Integrate `mlx-vlm` into the Vision Agent
Open `verity/agents/vision.py`. Developer B has created a `VisionAgent` class with stubbed methods. You need to wire your local `mlx-vlm` inference calls into these three methods:
* `evaluate_alt_text()`: Pass the image and prompt; return the parsed `AltTextJudgment`.
* `evaluate_focus_visible()`: Pass the before/after images; return the parsed `FocusVisibleJudgment`.
* `localise_contrast_regions()`: Pass the image and selector; return the parsed `ContrastRegionLocalisation`.

Ensure you use constrained decoding (JSON schema enforcement) during your inference calls so the model's output maps perfectly to the Pydantic classes we defined.

### 3. Run the Precision Evaluation
Once the VLM is wired in, execute the Spike A corpus harness (Task A2.3) using these newly wired agents. We will then compare the results against the precision bar we defined on Monday to make the joint descope decision for ADR-0002.
