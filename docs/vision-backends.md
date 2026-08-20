# Vision backends — running the model, and where vLLM fits

The vision *judgments* (rubrics + schemas in `verity/agents/vision.py`) are
fixed. Where the model runs is a swappable backend
(`verity/agents/vision_backends.py`), chosen at runtime. Agent code never
changes when the backend does.

```
VisionAgent ── backend.complete_json(system, user, images) ──▶ dict | None
                                                                │
                          validate against the judgment schema  │
                                     │                          │
                              valid  │      invalid / None      │
                                     ▼                          ▼
                              the judgment                  unknown
```

**Abstention is the only way a call can fail.** A backend that is down, a
model that emits garbage, or output that violates the schema all resolve to
`unknown` — never a fabricated answer. That is the fabrication defence, kept
even at the transport layer.

## Backends

| `VERITY_VISION_BACKEND` | Runs on | Use |
|---|---|---|
| `abstain` (default) | nothing | un-provisioned checkout; every judgment `unknown` |
| `mlx` | Apple Silicon, Metal | **the plan's primary** — Qwen3-VL via mlx-vlm |
| `openai` | any OpenAI-compatible server | local vLLM/Ollama on an NVIDIA box; LM Studio |

## Running Spike A on this Mac (M4, Metal) — the primary path

vLLM is **not** an option here: it is CUDA/NVIDIA-only and this machine has
no NVIDIA GPU. mlx-vlm is the Metal-native equivalent and the sanctioned
primary.

```bash
cd ~/Desktop/verity
uv pip install mlx-vlm jinja2   # jinja2 is needed for the chat template and mlx-vlm does not always pull it

# Pick a 4-bit Qwen VL build (~5-8 GB download, one time).
export VERITY_VISION_BACKEND=mlx
export VERITY_MLX_MODEL="mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
```

Then run the harness — it renders the vision gallery, runs the alt-text
judge on all 48 cases, and reports precision as a Wilson 95% interval:

```bash
uv run python -m eval.vision.measure
```

Results land in `eval/vision/results.json`; record the headline numbers and
the hardware (cold-load seconds, tokens/sec, peak memory) into
[`docs/measurements/spike-a.md`](measurements/spike-a.md).

**16 GB caveat (measure, don't assume):** an 8B VL model at Q4 is ~8–12 GB;
the research brief recommends 32 GB for comfort. On 16 GB it should run
*serialised* (one model slot — which is the plan's design), but expect it to
be tight and slower than the M4 Max benchmarks. That is exactly what Spike A
exists to find out. If it won't fit or is too slow, the Week 2 gate's own
fallback is **descope Vision to OCR + contrast-only** — not reach for cloud.

## Where vLLM legitimately fits — later

vLLM enters through the `openai` backend, unchanged agent code:

```bash
# On a Linux/NVIDIA box you control:
vllm serve Qwen/Qwen2.5-VL-7B-Instruct --port 8000

# From the scanner:
export VERITY_VISION_BACKEND=openai
export VERITY_VISION_BASE_URL="http://<gpu-box>:8000/v1"
export VERITY_VISION_MODEL="Qwen/Qwen2.5-VL-7B-Instruct"
```

This is the **Week 18 Linux/CUDA secondary path**, and it is fine when the
box is one you self-host.

**A remote/cloud endpoint is an ADR-level decision, not a config tweak.**
Pointing this at a rented GPU sends rendered page screenshots off the
machine, which crosses two hard project lines: the *self-hostable, no-cloud*
constraint that is the differentiator vs. Evinced, and the prompt-injection
threat model (Verity ingests arbitrary web pages). Acceptable as a one-off to
get a Spike A number if this Mac genuinely can't; not acceptable as the
shipped architecture. Either way it needs Nikhil's sign-off and an ADR,
because it changes the project's positioning — it is not a unilateral swap.
