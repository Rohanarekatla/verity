"""
B15.2′ — fix evaluation on injected defects (Track B, Week 15).

Does the verifier-gated fix loop (B15.1′) actually fix things, and does it ever
accept a patch that breaks something else? Measured on defects we injected
ourselves, so the right answer is known:

    clean page  --inject one defect-->  broken page  --fix loop-->  patched page

For every case:

- **fixed** — the loop accepted a patch AND an independent full re-scan of the
  patched page no longer reports the injected defect;
- **accepted regression** — an accepted patch whose page has a failing finding
  the CLEAN original did not have. The loop's own acceptance rule should make
  this impossible; this is the independent check (Week 15 gate: exactly 0);
- **patch size** (lines changed), **attempts**, **$/fix**.

Gate (plan v2, Sun 6 Dec): >= 60% of injected name / label / alt / contrast
defects fixed, with 0 accepted regressions.

    uv run python -m eval.fix_eval --patcher rules
    uv run python -m eval.fix_eval --patcher anthropic:claude-sonnet-5-5 --budget 5
    uv run python -m eval.fix_eval --patcher ollama:qwen3:14b

Published LLM-repair studies report fix rates without a regression rate; the
point of reporting both is that a fix rate alone is a vanity metric.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "fixtures"

GATE_FIX_RATE = 0.60
GATE_FAMILIES = ("name", "label", "alt", "contrast")


@dataclass(frozen=True)
class FixCase:
    id: str
    family: str          # name | label | alt | contrast | keyboard | focus
    page: str            # clean fixture under data/fixtures
    injector: str        # module in eval.inject, or "aria:<name>" for aria_misuse
    selector: str
    scs: tuple           # criteria the defect may be reported under (axe tags vary by rule)
    target: str          # element id the defect lands on


CASES: tuple[FixCase, ...] = (
    FixCase("alt-1", "alt", "images.html", "strip_alt", "#content-photo", ("1.1.1",), "content-photo"),
    FixCase("alt-2", "alt", "elements.html", "strip_alt", "#box-img", ("1.1.1",), "box-img"),
    FixCase("label-1", "label", "apg/dialog-pass.html", "detach_label", "label", ("4.1.2", "1.3.1", "3.3.2"), "street"),
    FixCase("label-2", "label", "apg/combobox-pass.html", "detach_label", "label", ("4.1.2", "1.3.1", "3.3.2"), "state"),
    FixCase("name-1", "name", "apg/menu-button-pass.html", "aria:strip_accessible_name", "#actions", ("4.1.2",),
            "actions"),
    FixCase("name-2", "name", "apg/disclosure-pass.html", "aria:strip_accessible_name", "#faq-1", ("4.1.2",), "faq-1"),
    FixCase("contrast-1", "contrast", "contrast-pass.html", "reduce_contrast", "#ok-contrast-text", ("1.4.3",),
            "ok-contrast-text"),
    FixCase("focus-1", "focus", "apg/disclosure-pass.html", "outline_none", "#faq-1", ("2.4.7",), "faq-1"),
    FixCase("tabindex-1", "keyboard", "apg/disclosure-pass.html", "positive_tabindex", "#faq-1", ("2.4.3",), "faq-1"),
)


@dataclass
class CaseResult:
    case: FixCase
    found: bool                       # the injected defect was reported at all
    accepted: bool = False
    fixed: bool = False
    accepted_regression: bool = False
    attempts: int = 0
    lines_changed: int = 0
    cost_usd: float = 0.0
    notes: list[str] = field(default_factory=list)
    diff: str = ""


def inject(case: FixCase, html: str) -> str:
    import importlib

    if case.injector.startswith("aria:"):
        from eval.inject.aria_misuse import INJECTORS

        return INJECTORS[case.injector.split(":", 1)[1]].inject(html, case.selector)
    mod = importlib.import_module(f"eval.inject.{case.injector}")
    return mod.inject(html, case.selector)


def _failing(findings: list[dict]) -> list[dict]:
    return [f for f in findings if f.get("outcome") == "fail" and not f.get("waived")]


def _target_finding(findings: list[dict], case: FixCase) -> Optional[dict]:
    from eval.precision_recall import finding_targets

    for f in _failing(findings):
        if (f.get("sc") or {}).get("id") in case.scs and case.target in finding_targets(f):
            return f
    return None


def run_case(case: FixCase, *, scan_fn: Callable[[str], list[dict]], patcher) -> CaseResult:
    from verity.remediation.fix_loop import _key, fix_finding

    clean_html = (FIXTURES / case.page).read_text(encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="verity-fixeval-") as tmp:
        root = Path(tmp) / "site"
        root.mkdir()
        (root / "clean.html").write_text(clean_html, encoding="utf-8")
        clean_findings = scan_fn(str(root / "clean.html"))
        (root / "clean.html").unlink()
        page = Path(case.page).name
        (root / page).write_text(inject(case, clean_html), encoding="utf-8")
        before = scan_fn(str(root / page))
        target = _target_finding(before, case)
        if target is None:
            return CaseResult(case, found=False, notes=["the injected defect was not reported, so there is nothing "
                                                        "to fix (a detection gap, not a fix failure)"])
        fr = fix_finding(target, project_root=root, page=page, scan_fn=scan_fn, patcher=patcher, before=before)
        res = CaseResult(case, found=True, accepted=fr.accepted, attempts=len(fr.attempts),
                         lines_changed=fr.lines_changed, cost_usd=fr.cost_usd, diff=fr.diff,
                         notes=list(fr.handoff))
        if fr.accepted:
            fr.apply_to(root)
            after = scan_fn(str(root / page))         # independent re-scan of the real patched page
            res.fixed = _target_finding(after, case) is None
            clean_keys = {_key(f) for f in _failing(clean_findings)}
            regressions = [f for f in _failing(after) if _key(f) not in clean_keys]
            res.accepted_regression = bool(regressions)
            if regressions:
                res.notes.append(f"REGRESSION: {regressions[0].get('rule_id')} at "
                                 f"{(regressions[0].get('evidence') or {}).get('dom_selector')}")
        return res


def fix_metrics(results: list[CaseResult]) -> dict:
    found = [r for r in results if r.found]
    gate = [r for r in found if r.case.family in GATE_FAMILIES]
    fixed = [r for r in found if r.fixed]
    gate_fixed = [r for r in gate if r.fixed]
    accepted = [r for r in found if r.accepted]
    return {
        "cases": len(results), "found": len(found), "fixed": len(fixed),
        "fix_rate": len(fixed) / len(found) if found else None,
        "gate_fix_rate": len(gate_fixed) / len(gate) if gate else None,
        "accepted": len(accepted),
        "accepted_regressions": sum(r.accepted_regression for r in results),
        "regression_rate": (sum(r.accepted_regression for r in accepted) / len(accepted)) if accepted else 0.0,
        "mean_lines_changed": fmean([r.lines_changed for r in fixed]) if fixed else None,
        "mean_attempts": fmean([r.attempts for r in found]) if found else None,
        "cost_total": sum(r.cost_usd for r in results),
        "cost_per_fix": (sum(r.cost_usd for r in results) / len(fixed)) if fixed else None,
        "gate_passed": bool(gate) and len(gate_fixed) / len(gate) >= GATE_FIX_RATE
                       and not any(r.accepted_regression for r in results),
    }


def render(results: list[CaseResult], metrics: dict) -> str:
    lines = ["| case | family | SC | reported | accepted | fixed | regression | attempts | lines | $ | notes |",
             "|---|---|---|---|---|---|---|--:|--:|--:|---|"]
    for r in results:
        yn = lambda b: "yes" if b else "no"  # noqa: E731
        lines.append(f"| {r.case.id} | {r.case.family} | {'/'.join(r.case.scs)} | {yn(r.found)} | {yn(r.accepted)} | "
                     f"{yn(r.fixed)} | {'**YES**' if r.accepted_regression else 'no'} | {r.attempts} | "
                     f"{r.lines_changed} | {r.cost_usd:.4f} | {'; '.join(r.notes)[:120]} |")
    m = metrics
    rate = lambda x: "—" if x is None else f"{x:.0%}"  # noqa: E731
    lines += ["", f"**Fixed {m['fixed']}/{m['found']} ({rate(m['fix_rate'])}); gate families "
              f"{rate(m['gate_fix_rate'])} (target ≥ {GATE_FIX_RATE:.0%}); accepted regressions "
              f"{m['accepted_regressions']} (target 0) → {'PASS' if m['gate_passed'] else 'FAIL'}.**"]
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    from verity.remediation.fix_loop import LLMPatcher, RulePatcher

    p = argparse.ArgumentParser(description="Fix-loop evaluation on injected defects")
    p.add_argument("--patcher", default="rules", help="'rules' or a provider spec (anthropic:…, ollama:…)")
    p.add_argument("--budget", type=float, default=None, help="USD cap for model calls")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    if args.patcher == "rules":
        patcher = RulePatcher()
    else:
        from eval.agentbench.providers import CostLedger, make_provider

        patcher = LLMPatcher(make_provider(args.patcher, ledger=CostLedger(cap_usd=args.budget)))

    def scan_fn(path: str) -> list[dict]:
        from verity.orchestrator.main import scan_url

        report = asyncio.run(scan_url(Path(path).as_uri(), timeout=120.0))
        return [json.loads(f.model_dump_json()) for f in report.findings]

    results = [run_case(c, scan_fn=scan_fn, patcher=patcher) for c in CASES]
    metrics = fix_metrics(results)
    text = render(results, metrics)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    return 0 if metrics["gate_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
