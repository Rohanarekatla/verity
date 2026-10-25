"""
B10.4 — model-load vs inference timing, per provider.

The original Week 10 question, kept in plan v2: is a run dominated by loading
the model or by running it? For local models the answer decides whether runs
should be batched per model (load once) and how many can run in parallel; for
remote APIs there is no load to see, and wall clock is the honest number.

    uv run python -m eval.agentbench.providers.timing ollama:qwen3:8b
    uv run python -m eval.agentbench.providers.timing anthropic:claude-haiku-5-5 --warm 3

For a provider that can `unload()` (Ollama), the first call is made cold —
model evicted first — and the rest warm. Remote providers report wall clock
only, and `load_s` is "n/a", never 0.

Output is one JSON object, ready to paste into
docs/measurements/agentbench-pilot.md.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from typing import Optional

from eval.agentbench.providers.base import BaseProvider, Completion, Message

PROBE = (
    "You are a web agent. The page's accessibility tree is:\n"
    "RootWebArea 'Sign in'\n  textbox 'Email'\n  textbox 'Password'\n  button 'Sign in'\n"
    "Reply with the single next action, e.g. click('Sign in')."
)


def _mean(xs: list[Optional[float]]) -> Optional[float]:
    vals = [x for x in xs if x is not None]
    return round(statistics.fmean(vals), 4) if vals else None


def profile(provider: BaseProvider, *, warm: int = 3, max_tokens: int = 32) -> dict:
    """One cold call (if the provider can unload) then `warm` warm calls."""
    calls: list[tuple[str, Completion]] = []
    if hasattr(provider, "unload"):
        provider.unload()
        calls.append(("cold", provider.complete([Message(role="user", content=PROBE)],
                                                max_tokens=max_tokens, cache=False)))
    for _ in range(warm):
        calls.append(("warm", provider.complete([Message(role="user", content=PROBE)],
                                                max_tokens=max_tokens, cache=False)))

    def summarise(kind: str) -> Optional[dict]:
        cs = [c for k, c in calls if k == kind]
        if not cs:
            return None
        return {
            "calls": len(cs),
            "wall_s": _mean([c.timing.wall_s for c in cs]),
            "load_s": _mean([c.timing.load_s for c in cs]) if provider.local else "n/a (remote)",
            "inference_s": _mean([c.timing.inference_s for c in cs]),
            "output_tokens": _mean([float(c.usage.output_tokens) for c in cs]),
        }

    cold, hot = summarise("cold"), summarise("warm")
    verdict = None
    if cold and hot and isinstance(cold["load_s"], float) and hot["inference_s"]:
        verdict = "load-dominant" if cold["load_s"] > hot["inference_s"] else "inference-dominant"
    return {"provider": provider.name, "model": provider.model, "cold": cold, "warm": hot,
            "per_call_verdict": verdict}


def main(argv: Optional[list[str]] = None) -> int:
    from eval.agentbench.providers import make_provider

    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("spec", help="provider:model, e.g. ollama:qwen3:8b")
    p.add_argument("--warm", type=int, default=3)
    args = p.parse_args(argv)
    print(json.dumps(profile(make_provider(args.spec), warm=args.warm), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
