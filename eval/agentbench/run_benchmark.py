"""
A12.1′/A12.2′ benchmark CLI — run the pre-registered benchmark, then build the
results store and dashboards.

    uv run python -m eval.agentbench.run_benchmark \
        --model frontier=anthropic:claude-... \
        --model local-a=ollama:qwen3:8b \
        --trials 12 --budget 150 --workers 2 \
        --out runs/v1

The run is resumable: re-running the same command continues from
`runs/v1/records.jsonl` and keeps counting spend from `runs/v1/ledger*.jsonl`.
The budget is a hard gate — the run stops before it would cross `--budget`,
never after. Success rates are NOT printed here: "no peeking" (pre-reg §9). Use
`eval.agentbench.analysis` (or the dashboards this writes) once the run is done.

Needs provider keys in the environment (ANTHROPIC_API_KEY / OPENAI_API_KEY) or a
local Ollama, and the vendored MiniWoB tasks present. Only the tree agent is
runnable today; the browser-use / screen-reader agents arrive in Week 13.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.agentbench.results_store import build_dashboards
from eval.agentbench.runner import run_benchmark


def _parse_models(pairs: list[str]) -> dict[str, str]:
    models: dict[str, str] = {}
    for p in pairs:
        label, sep, spec = p.partition("=")
        if not sep or not label or not spec:
            raise SystemExit(f"--model must be label=provider:model, got {p!r}")
        models[label] = spec
    return models


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the AgentBench benchmark (A12.1′).")
    ap.add_argument("--model", action="append", default=[], metavar="LABEL=SPEC",
                    help="a model, e.g. frontier=anthropic:claude-sonnet-5-5 (repeatable)")
    ap.add_argument("--trials", type=int, default=1, help="trials per (task × defect × model)")
    ap.add_argument("--budget", type=float, required=True, help="hard USD cap for the whole run")
    ap.add_argument("--workers", type=int, default=1, help="parallel browsers; each gets budget/workers")
    ap.add_argument("--out", required=True, help="run directory (records, traces, ledgers, dashboards)")
    ap.add_argument("--no-resume", action="store_true", help="start fresh instead of continuing --out")
    ap.add_argument("--headed", action="store_true", help="show the browser (debugging)")
    args = ap.parse_args()

    models = _parse_models(args.model)
    if not models:
        ap.error("give at least one --model LABEL=SPEC")

    out = Path(args.out)
    report = run_benchmark(
        models, out_dir=out, trials=args.trials, cap_usd=args.budget,
        workers=args.workers, resume=not args.no_resume, headless=not args.headed,
    )

    print(f"planned={report.planned} already_done={report.already_done} "
          f"ran={report.run} spend=${report.cost_usd:.4f}")
    if report.excluded:
        print("excluded: " + ", ".join(f"{k}={v}" for k, v in sorted(report.excluded.items())))
    if report.budget_stopped:
        print("** budget cap reached — run stopped short; re-run with a higher --budget to continue")

    # Build the results store + dashboards from whatever completed so far.
    built = build_dashboards(out / "records.jsonl", out / "dashboards")
    print(f"dashboards: {built['episodes']} episodes -> {built['markdown']} / {built['html']} / {built['parquet']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
