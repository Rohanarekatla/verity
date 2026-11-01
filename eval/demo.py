"""
Week 18 — the 3-minute demo, as a script (plan v2: "agent fails on a broken
page → Verity pins and confirms the defect → fix loop patches it → agent
succeeds").

    uv run python -m eval.demo --model ollama:qwen3:14b
    uv run python -m eval.demo --model anthropic:claude-sonnet-5-5 --budget 1

Every step is a real Verity call — nothing is staged:

1. `verity agent-check` with confirmation (B14.1′) on `data/demo/checkout/`:
   the tree agent tries "Place the order" and fails; Verity localises the
   failure to the unnamed button and CONFIRMS it from the live page.
2. The verifier-gated fix loop (B15.1′) patches a sandbox copy with the same
   model; Verity re-scans and accepts only if the defect is gone and nothing
   new broke.
3. agent-check again on the patched copy: the agent completes the task.

If the agent succeeds in step 1 by clicking a control with no accessible name
(it guessed from position — seen with qwen3:4b on 31 Oct), the demo says so
and continues: the defect is real regardless, and step 3 shows the agent
acting on a real name instead of a guess. A pass through a NAMED control
still stops the demo — then the page has nothing to show.

The original demo page is never modified; the patched copy is written to
`--out` (default `runs/demo/`), with the diff, so the recording can show it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
DEMO = REPO / "data" / "demo" / "checkout"
TASK = "Place the order"
SUCCESS = {"element": {"selector": "#status", "text_contains": "Order placed"}}
PATCH_SCHEMA = {"type": "object", "required": ["old", "new", "rationale"],
                "properties": {"old": {"type": "string"}, "new": {"type": "string"}, "rationale": {"type": "string"}}}


def _say(step: str, text: str) -> None:
    print(f"\n[{step}] {text}", flush=True)


def _trace(result) -> None:
    """What the agent saw first, and every action it took — so a pass or a
    fail can be read, not just believed."""
    steps = getattr(result.episode, "steps", None) or []
    if steps:
        print("      the accessibility tree the agent saw:")
        print("        " + (steps[0].observation or "").replace("\n", "\n        "))
    for i, s in enumerate(steps, 1):
        err = f"  -> error: {s.error}" if s.error else ""
        print(f"      step {i}: {s.action}{err}")


def _clicked(result) -> Optional[tuple[str, str]]:
    """(role, name) of the element the agent's last click hit, read from the
    tree it saw at that step — so we can say whether it acted on a name or a guess."""
    import re

    from eval.agentbench.verify_injection import parse_tree

    for s in reversed(getattr(result.episode, "steps", None) or []):
        m = re.match(r"click bid=(\S+)", s.action or "")
        if m:
            node = next((n for n in parse_tree(s.observation or "") if n.bid == m.group(1)), None)
            return (node.role, node.name) if node else None
    return None


def _check(url: str, provider, *, headless: bool, max_tokens: int):
    from eval.agentbench.agents.tree_agent import TreeAgent
    from eval.agentbench.evaluators import evaluate, observation_from_page
    from eval.agentbench.loop_guard import LoopGuard
    from eval.agentbench.web_env import WebEnv
    from verity.agent_check.check import agent_check
    from verity.agent_check.confirm import make_confirm_fn

    def success_fn(env):
        return evaluate(SUCCESS, observation_from_page(env.page, SUCCESS), task_id="demo").outcome

    with WebEnv(url, goal=TASK, headless=headless) as env:
        return agent_check(url, TASK, agent=TreeAgent(provider, max_tokens=max_tokens, loop_guard=LoopGuard()),
                           env=env,
                           success_fn=success_fn, confirm_fn=make_confirm_fn(env))


def main(argv: Optional[list[str]] = None) -> int:
    from eval.agentbench.providers import CostLedger, make_provider
    from verity.orchestrator.main import scan_url
    from verity.remediation.fix_loop import LLMPatcher, fix_finding

    p = argparse.ArgumentParser(description="Verity end-to-end demo")
    p.add_argument("--model", required=True, help="provider spec for the agent and the patcher")
    p.add_argument("--budget", type=float, default=None)
    p.add_argument("--out", type=Path, default=REPO / "runs" / "demo")
    p.add_argument("--headed", action="store_true")
    p.add_argument("--max-tokens", type=int, default=2048,
                   help="per model call; local reasoning models need room to think before answering")
    args = p.parse_args(argv)

    extra = {}
    if args.model.startswith("ollama:"):
        name = args.model.split(":", 1)[1]
        # gpt-oss only accepts a thinking level; other local models can turn it off.
        extra = {"think": "low" if name.startswith("gpt-oss") else False, "timeout": 600.0}
    provider = make_provider(args.model, ledger=CostLedger(cap_usd=args.budget),
                             allow_unpriced=args.budget is None, **extra)
    patch_provider = provider
    if extra:
        # The patcher must return one {"old","new","rationale"} object. A small local
        # model otherwise reasons aloud in its answer and is cut off before any JSON
        # (qwen3:4b, 31 Oct) — so constrain the shape; the verifier still gates the patch.
        patch_provider = make_provider(args.model, ledger=provider.ledger, allow_unpriced=args.budget is None,
                                       format=PATCH_SCHEMA, **extra)
    work = args.out / "site"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(DEMO, work)
    page = work / "index.html"

    _say("1/3", f"An AI agent tries to '{TASK}' through the accessibility tree…")
    first = _check(page.as_uri(), provider, headless=not args.headed, max_tokens=args.max_tokens)
    _trace(first)
    print(f"      verdict: {first.verdict.upper()}")
    if first.verdict == "inconclusive":
        print("      the model never produced a valid action, so this run says nothing about the page.")
        print("      (Answers cut off? Raise --max-tokens. Otherwise try a stronger model.)")
        return 1
    if first.succeeded:
        hit = _clicked(first)
        if hit and not hit[1].strip():
            # The honest pivot (31 Oct): on a small page an agent can infer the
            # right control from position. It succeeded by guessing — the
            # defect is still real, and guessing does not scale.
            print(f"      the agent succeeded by GUESSING: it clicked a {hit[0]} with no accessible name,")
            print("      inferring from its position. On a bigger page that guess fails;")
            print("      for a screen-reader user it is just 'button, button, button'.")
        else:
            print("      the agent succeeded through a named control — this page has nothing to demonstrate")
            return 1
    else:
        f = first.findings[0]
        print(f"      Verity: SC {f.sc.id} {f.sc.name} — {f.message}")
        print(f"      provenance: {f.provenance.value.upper()} (confirmed from the live page)"
              if f.provenance.value == "authoritative" else "      provenance: needs review (not confirmed)")

    _say("2/3", "Verity's fix loop patches a sandbox copy and re-scans before accepting…")

    def scan_fn(path: str) -> list[dict]:
        report = asyncio.run(scan_url(Path(path).as_uri(), timeout=120.0))
        return [json.loads(x.model_dump_json()) for x in report.findings]

    before = scan_fn(str(page))
    unnamed = [x for x in before if x["outcome"] == "fail" and x["sc"]["id"] == "4.1.2"]
    print(f"      Verity's scan: {len(unnamed)} SC 4.1.2 failure(s) on the page, whatever the agent did")
    target =next((x for x in before if x["outcome"] == "fail" and x["sc"]["id"] == "4.1.2"
                   and "place-order" in (x["evidence"].get("dom_selector") or "")), None)
    if target is None:
        print("      the scan did not report the unnamed button — stopping (a detection gap, reported honestly)")
        return 1
    fix = fix_finding(target, project_root=work, page="index.html", scan_fn=scan_fn,
                      patcher=LLMPatcher(patch_provider, max_tokens=args.max_tokens), before=before)
    if not fix.accepted:
        print("      no patch was accepted:\n        " + "\n        ".join(fix.handoff))
        return 1
    fix.apply_to(work)
    (args.out / "fix.diff").write_text(fix.diff, encoding="utf-8")
    print(f"      accepted after {len(fix.attempts)} attempt(s); {fix.lines_changed} line(s) changed:\n")
    print("      " + fix.diff.replace("\n", "\n      "))

    _say("3/3", "The same agent tries again on the fixed page…")
    second = _check(page.as_uri(), provider, headless=not args.headed, max_tokens=args.max_tokens)
    _trace(second)
    print(f"      verdict: {second.verdict.upper()}")
    hit = _clicked(second)
    if second.succeeded and hit and hit[1].strip():
        print(f"      this time it clicked {hit[0]} \"{hit[1]}\" — by name, not by guess")
    print(f"\nTotal model spend: ${provider.ledger.total_usd:.4f}" if provider.ledger else "")
    return 0 if second.succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
