"""
A10.4 pilot CLI — run the W10 pilot and write its measurements.

A thin wrapper around `pilot.run_pilot` + `pilot.format_report`: build the
providers with a shared budget ledger, run the matrix, write the report.

    uv run python -m eval.agentbench.run_pilot \
        --frontier anthropic:claude-... --local ollama:... \
        --budget 5.00 --out docs/measurements/agentbench-pilot.md

Needs provider keys in the environment (ANTHROPIC_API_KEY / OPENAI_API_KEY, or a
local Ollama). The budget cap is a gate: the ledger refuses a call before it
would cross `--budget`, so the run's worst-case spend is bounded.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.agentbench.pilot import PILOT_TRIALS, format_report, run_pilot
from eval.agentbench.providers import CostLedger, make_provider


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the AgentBench W10 pilot.")
    ap.add_argument("--frontier", help="frontier model spec, e.g. anthropic:claude-...")
    ap.add_argument("--local", help="local model spec, e.g. ollama:llama3.1")
    ap.add_argument("--budget", type=float, required=True, help="hard USD cap for the whole run")
    ap.add_argument("--trials", type=int, default=PILOT_TRIALS)
    ap.add_argument("--out", default="docs/measurements/agentbench-pilot.md")
    ap.add_argument("--headed", action="store_true", help="show the browser (debugging)")
    args = ap.parse_args()

    if not args.frontier and not args.local:
        ap.error("give at least one of --frontier / --local")

    # One ledger shared across providers, so the cap is on the whole run.
    ledger = CostLedger(cap_usd=args.budget)
    models = {}
    if args.frontier:
        models["frontier"] = make_provider(args.frontier, ledger=ledger)
    if args.local:
        models["local"] = make_provider(args.local, ledger=ledger)

    cells = run_pilot(models, trials=args.trials, headless=not args.headed)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(format_report(cells), encoding="utf-8")
    print(f"pilot complete: {len(cells)} cells, ${sum(c.cost_total for c in cells):.4f} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
