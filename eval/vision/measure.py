"""
Spike A measurement harness (B2.1 / B2.2).

Renders the vision gallery through the real worker to get element crops, runs
the alt-text meaningfulness judge on every (crop, alt) case, and reports
precision with a Wilson confidence interval — the exact form the Week 2 bar
is stated in (lower bound of the 95% CI ≥ 90%, point ≥ 95%).

    # honest default: no model wired, everything abstains -> nothing to measure
    uv run python -m eval.vision.measure

    # the real run:
    uv pip install mlx-vlm
    export VERITY_VISION_BACKEND=mlx
    export VERITY_MLX_MODEL="mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
    uv run python -m eval.vision.measure

A "finding" here is a verdict of `no` (alt is not meaningful). Precision is
the fraction of those verdicts that are correct — i.e. the alt really was a
placeholder. A `no` on a genuinely meaningful alt is a false positive, and FP
is the metric the whole project is gated on. `yes` and `unknown` produce no
finding and so don't enter the precision denominator; abstention is tracked
separately as a health signal.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from collections import Counter
from pathlib import Path

from verity.agents.vision import VisionAgent
from verity.orchestrator.rpc_client import RPCClient

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
GALLERY = REPO / "data" / "fixtures" / "vision-gallery.html"
CASES = HERE / "cases.json"
RESULTS = HERE / "results.json"
WORKER = ["node", str(REPO / "node-worker" / "dist" / "rpc" / "server.js")]

Z = 1.959963984540054  # 95%


def wilson_interval(successes: int, n: int) -> tuple[float, float, float]:
    """Return (point, lower, upper) for a proportion, Wilson score, 95%."""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = successes / n
    denom = 1 + Z * Z / n
    center = (p + Z * Z / (2 * n)) / denom
    margin = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / denom
    return (p, max(0.0, center - margin), min(1.0, center + margin))


async def render_crops() -> dict[str, str]:
    """Render the gallery and return {image_id: crop_path} for every v-* image."""
    client = RPCClient(command=WORKER, default_timeout=120.0)
    await client.start()
    try:
        render = await client.send_request("render", {"url": GALLERY.as_uri()})
        shots = render.get("element_screenshots", {})
        crops: dict[str, str] = {}
        for selector, capture in shots.items():
            # crops are keyed by CSS selector; our images use #v-<name> ids
            sid = selector.lstrip("#")
            if sid.startswith("v-"):
                crops[sid] = capture["path"]
        return crops
    finally:
        await client.stop()


def build_cases(crops: dict[str, str], spec: dict) -> list[dict]:
    """One meaningful case + one per placeholder, per image that rendered a crop."""
    cases: list[dict] = []
    placeholders = spec["placeholder_alts"]
    for image_id, info in spec["images"].items():
        crop = crops.get(image_id)
        if not crop:
            continue  # image didn't render a crop; skip rather than guess
        cases.append({"image_id": image_id, "crop": crop, "alt": info["good_alt"], "meaningful": True})
        for ph in placeholders:
            cases.append({"image_id": image_id, "crop": crop, "alt": ph, "meaningful": False})
    return cases


def run() -> int:
    spec = json.loads(CASES.read_text())
    crops = asyncio.run(render_crops())
    if not crops:
        print("No image crops rendered — is the node worker built?  "
              "cd node-worker && npm run build")
        return 1
    print(f"rendered {len(crops)} image crops")

    cases = build_cases(crops, spec)
    agent = VisionAgent.from_env()
    backend = type(agent.backend).__name__
    print(f"backend: {backend}  |  cases: {len(cases)}")

    verdicts: list[dict] = []
    latencies: list[float] = []
    for i, c in enumerate(cases, 1):
        t0 = time.time()
        judgment = agent.evaluate_alt_text(c["crop"], c["alt"])
        dt = time.time() - t0
        latencies.append(dt)
        verdicts.append({**c, "verdict": judgment.meaningful, "seconds": round(dt, 3)})
        if i % 10 == 0:
            print(f"  {i}/{len(cases)}")

    # A "no" is a finding. Precision = correct "no"s / all "no"s.
    findings = [v for v in verdicts if v["verdict"] == "no"]
    true_pos = sum(1 for v in findings if not v["meaningful"])
    false_pos = sum(1 for v in findings if v["meaningful"])
    total_negatives = sum(1 for v in verdicts if not v["meaningful"])
    abstained = sum(1 for v in verdicts if v["verdict"] == "unknown")

    p_point, p_lower, p_upper = wilson_interval(true_pos, len(findings))
    recall = true_pos / total_negatives if total_negatives else 0.0
    dist = Counter(v["verdict"] for v in verdicts)

    result = {
        "backend": backend,
        "model": __import__("os").environ.get("VERITY_MLX_MODEL", "n/a"),
        "cases": len(cases),
        "verdict_distribution": dict(dist),
        "precision": {
            "findings": len(findings),
            "true_positive": true_pos,
            "false_positive": false_pos,
            "point": round(p_point, 4),
            "wilson95_lower": round(p_lower, 4),
            "wilson95_upper": round(p_upper, 4),
        },
        "recall_on_placeholders": round(recall, 4),
        "abstention_rate": round(abstained / len(cases), 4) if cases else 0.0,
        "latency_seconds": {
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
            "max": round(max(latencies), 3) if latencies else 0.0,
        },
        "bar": "wilson95_lower >= 0.90 and point >= 0.95",
        "gate": "PASS" if (p_lower >= 0.90 and p_point >= 0.95) else "FAIL",
        "verdicts": verdicts,
    }
    RESULTS.write_text(json.dumps(result, indent=2))

    print("\n=== Spike A — alt-text meaningfulness ===")
    print(f"  backend            : {backend}")
    print(f"  verdicts           : {dict(dist)}")
    print(f"  findings (verdict=no): {len(findings)}  (TP {true_pos}, FP {false_pos})")
    print(f"  precision          : {p_point:.3f}  (95% CI {p_lower:.3f}–{p_upper:.3f})")
    print(f"  recall on placeholders: {recall:.3f}")
    print(f"  abstention rate    : {result['abstention_rate']:.3f}")
    print(f"  latency mean/max   : {result['latency_seconds']['mean']}s / {result['latency_seconds']['max']}s")
    print(f"  bar                : lower ≥ 0.90 and point ≥ 0.95")
    print(f"  GATE               : {result['gate']}")
    if backend == "AbstainBackend":
        print("\n  (AbstainBackend: no model wired — every verdict is `unknown`, so there\n"
              "   is nothing to measure. Provision a backend and re-run. This is the\n"
              "   honest empty result, not a pass.)")
    print(f"\n  full results -> {RESULTS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
