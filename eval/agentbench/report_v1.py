"""
B12.2′ / B12.3′ — the pre-registered results tables and the cost model
(Track B, Week 12).

Rohan's dashboards (A12.2′, `results_store`) show success by cell and the raw
paired gap. This module produces the *confirmatory* tables
`docs/agentbench/results-v1.md` must report, in the order and with the rules
the pre-registration fixes:

    §1  kill criterion — read FIRST, before any defect comparison
    §3  H1: paired effect per (model × name defect), exact McNemar, Holm
        within the family, Bonett–Price interval, cluster-bootstrap
        sensitivity; a cell losing >10% of pairs is UNRELIABLE and leaves the
        family (Holm denominator shrinks, and the table says so)
    §4  H2 / H3: difference in differences between agent types
    §5  H4: tokens per successful task, Wilcoxon on paired token totals
    §6  exclusions, by reason
    B12.3′  cost model: $/episode, $/successful task, tokens/step, clean vs
        defect

"Supported" is the conservative headline: Holm p < 0.05 AND the Bonett–Price
interval excludes 0 in the predicted direction AND the task-cluster bootstrap
interval agrees (pre-reg §8.4). Anything else is reported, never hidden.

    uv run python -m eval.agentbench.report_v1 runs/v1/records.jsonl --out runs/v1/results-v1-tables.md
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from eval.agentbench.analysis import (
    CLEAN,
    EpisodeRecord,
    difference_in_differences,
    holm,
    load_records,
    pair_episodes,
    paired_effect,
    tokens_per_success,
    wilcoxon_signed_rank,
    wilson,
)

KILL_THRESHOLD = 0.30
UNRELIABLE_DROP_SHARE = 0.10
ALPHA = 0.05
NAME_FAMILY = "name"
KEYBOARD_FAMILIES = ("keyboard", "focus")


def _defects(records: list[EpisodeRecord], families: tuple[str, ...]) -> list[str]:
    return sorted({r.defect for r in records if r.defect != CLEAN and (r.defect_family in families)})


def _models(records: list[EpisodeRecord], agent: str) -> list[str]:
    return sorted({r.model for r in records if r.agent == agent})


# --- §1 kill criterion -----------------------------------------------------------------

def kill_check(records: list[EpisodeRecord], *, agent: str = "tree") -> dict:
    """Clean-page success per model for the primary agent; the best must reach 30%."""
    per_model = {}
    for model in _models(records, agent):
        clean = [r for r in records if r.agent == agent and r.model == model and r.defect == CLEAN and r.usable]
        k = sum(1 for r in clean if r.outcome == "success")
        per_model[model] = wilson(k, len(clean))
    best = max((v[0] for v in per_model.values() if not math.isnan(v[0])), default=float("nan"))
    return {"per_model": per_model, "best": best, "threshold": KILL_THRESHOLD,
            "passed": (not math.isnan(best)) and best >= KILL_THRESHOLD}


# --- §3 H1 ------------------------------------------------------------------------------

def h1_table(records: list[EpisodeRecord], *, agent: str = "tree", n_boot: int = 5000) -> list[dict]:
    rows = []
    for model in _models(records, agent):
        for defect in _defects(records, (NAME_FAMILY,)):
            pairs, dropped = pair_episodes(records, defect=defect, agent=agent, model=model)
            total = len(pairs) + dropped
            if total == 0:
                continue
            e = paired_effect(pairs, dropped, n_boot=n_boot)
            e.update(agent=agent, model=model, defect=defect,
                     unreliable=(dropped / total) > UNRELIABLE_DROP_SHARE or not pairs)
            rows.append(e)
    family = {f"{r['model']}|{r['defect']}": r["mcnemar_p"] for r in rows if not r["unreliable"]}
    adjusted = holm(family)
    for r in rows:
        key = f"{r['model']}|{r['defect']}"
        r["holm_p"] = adjusted.get(key)
        r["family_size"] = len(family)
        r["supported"] = (
            r["holm_p"] is not None and r["holm_p"] < ALPHA
            and r["diff_ci"][0] > 0 and r["diff_ci_cluster_bootstrap"][0] > 0
        )
        r["disagree"] = (r["holm_p"] is not None and r["holm_p"] < ALPHA and r["diff_ci"][0] > 0) != (
            r["diff_ci_cluster_bootstrap"][0] > 0)
    return rows


# --- §4 H2 / H3 -------------------------------------------------------------------------

def did_table(records: list[EpisodeRecord], *, agent_x: str, agent_y: str, families: tuple[str, ...],
              n_boot: int = 5000) -> dict:
    """DiD (effect on X − effect on Y) per (model × defect). Empty rows => 'not tested'."""
    agents = {r.agent for r in records}
    if agent_x not in agents or agent_y not in agents:
        return {"tested": False, "why": f"no episodes for {agent_x if agent_x not in agents else agent_y}",
                "rows": []}
    defects = _defects(records, families)
    if not defects:
        return {"tested": False, "why": f"no defects of family {', '.join(families)} in the run", "rows": []}
    rows = []
    for model in sorted(set(_models(records, agent_x)) & set(_models(records, agent_y))):
        for defect in defects:
            px, _ = pair_episodes(records, defect=defect, agent=agent_x, model=model)
            py, _ = pair_episodes(records, defect=defect, agent=agent_y, model=model)
            if px and py:
                d = difference_in_differences(px, py, n_boot=n_boot)
                d.update(model=model, defect=defect, supported=d["ci"][0] > 0)
                rows.append(d)
    return {"tested": bool(rows), "why": "" if rows else "no shared tasks with pairs on both agents",
            "rows": rows}


# --- §5 H4 ------------------------------------------------------------------------------

def _pairs_with_records(records, *, agent, model, defect):
    clean = {(r.task_id, r.provider, r.trial): r for r in records
             if r.agent == agent and r.model == model and r.defect == CLEAN and r.usable}
    for r in records:
        if r.agent == agent and r.model == model and r.defect == defect and r.usable:
            c = clean.get((r.task_id, r.provider, r.trial))
            if c is not None:
                yield c, r


def h4_table(records: list[EpisodeRecord]) -> list[dict]:
    rows = []
    for agent in sorted({r.agent for r in records}):
        for model in _models(records, agent):
            clean = [r for r in records if r.agent == agent and r.model == model and r.defect == CLEAN]
            tps_clean = tokens_per_success(clean)
            for defect in sorted({r.defect for r in records if r.defect != CLEAN}):
                cell = [r for r in records if r.agent == agent and r.model == model and r.defect == defect]
                if not cell:
                    continue
                both = [(c, d) for c, d in _pairs_with_records(records, agent=agent, model=model, defect=defect)
                        if c.outcome == "success" and d.outcome == "success"]
                w = wilcoxon_signed_rank([d.tokens - c.tokens for c, d in both])
                tps_defect = tokens_per_success(cell)
                rows.append({
                    "agent": agent, "model": model, "defect": defect,
                    "clean_tokens_per_success": tps_clean, "defect_tokens_per_success": tps_defect,
                    "ratio": (tps_defect / tps_clean) if tps_clean and tps_defect else None,
                    "pairs_both_won": len(both), "wilcoxon_p": w["p"],
                })
    return rows


# --- §6 exclusions ------------------------------------------------------------------------

def exclusions(records: list[EpisodeRecord]) -> dict[str, int]:
    c = Counter()
    for r in records:
        if r.excluded_reason:
            c[r.excluded_reason] += 1
        elif r.outcome == "indeterminate":
            c["indeterminate"] += 1
    return dict(sorted(c.items()))


# --- B12.3′ cost model ----------------------------------------------------------------------

def cost_model(records: list[EpisodeRecord]) -> list[dict]:
    """
    Per (agent × model × defect): what an episode, a step and a SUCCESS cost.
    $/success charges failed episodes too — that is the real price of getting
    one task done — and is None when nothing succeeded (never "free").
    """
    cells: dict[tuple, list[EpisodeRecord]] = defaultdict(list)
    for r in records:
        cells[(r.agent, r.model, r.defect)].append(r)
    rows = []
    for (agent, model, defect), rs in sorted(cells.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] != CLEAN,
                                                                            kv[0][2])):
        usable = [r for r in rs if r.usable]
        wins = sum(1 for r in usable if r.outcome == "success")
        cost = sum(r.cost_usd for r in rs)          # excluded episodes still cost money
        steps = sum(r.steps for r in usable)
        tokens = sum(r.tokens for r in usable)
        rows.append({
            "agent": agent, "model": model, "defect": defect, "episodes": len(rs),
            "cost_total": cost, "cost_per_episode": cost / len(rs) if rs else None,
            "cost_per_success": cost / wins if wins else None,
            "tokens_per_step": tokens / steps if steps else None,
            "steps_per_episode": steps / len(usable) if usable else None,
        })
    clean = {(r["agent"], r["model"]): r for r in rows if r["defect"] == CLEAN}
    for r in rows:
        base = clean.get((r["agent"], r["model"]))
        r["cost_per_success_vs_clean"] = (
            r["cost_per_success"] / base["cost_per_success"]
            if base and r["defect"] != CLEAN and r["cost_per_success"] and base["cost_per_success"] else None)
    return rows


# --- rendering ------------------------------------------------------------------------------

def _p(x: Optional[float], digits: int = 1) -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{100 * x:.{digits}f}%"


def _n(x: Optional[float], fmt: str = "{:.4f}") -> str:
    return "—" if x is None or (isinstance(x, float) and math.isnan(x)) else fmt.format(x)


def render_markdown(records: list[EpisodeRecord], *, n_boot: int = 5000) -> str:
    out: list[str] = ["# Results v1 — pre-registered tables (generated by `eval/agentbench/report_v1.py`)", ""]

    k = kill_check(records)
    out += ["## 1. Kill criterion (read first)", "",
            "| model | clean success | 95% CI |", "|---|--:|---|"]
    for model, (p, lo, hi) in k["per_model"].items():
        out.append(f"| {model} | {_p(p)} | {_p(lo)}–{_p(hi)} |")
    verdict = "PASS — proceed" if k["passed"] else "FAIL — switch the suite to MiniWoB++ + simplest app tasks"
    out += ["", f"Best model: **{_p(k['best'])}** vs threshold {_p(KILL_THRESHOLD, 0)} → **{verdict}**.", ""]

    h1 = h1_table(records, n_boot=n_boot)
    fam = h1[0]["family_size"] if h1 else 0
    out += ["## 3. H1 — name defects vs the tree-only agent", "",
            f"Holm family size: {fam} (unreliable cells excluded from the family).", "",
            "| model | defect | pairs | dropped | clean | defect | Δ | 95% CI (B–P) | 95% CI (cluster) | McNemar p "
            "| Holm p | supported |",
            "|---|---|--:|--:|--:|--:|--:|---|---|--:|--:|---|"]
    for r in h1:
        flag = "UNRELIABLE" if r["unreliable"] else ("**yes**" if r["supported"] else "no")
        if r["disagree"] and not r["unreliable"]:
            flag += " (tests disagree — conservative shown)"
        out.append(
            f"| {r['model']} | {r['defect']} | {r['pairs']} | {r['dropped']} | {_p(r['clean_success'][0])} | "
            f"{_p(r['defect_success'][0])} | {_p(r['diff'])} | {_p(r['diff_ci'][0])}..{_p(r['diff_ci'][1])} | "
            f"{_p(r['diff_ci_cluster_bootstrap'][0])}..{_p(r['diff_ci_cluster_bootstrap'][1])} | "
            f"{_n(r['mcnemar_p'])} | {_n(r['holm_p'])} | {flag} |")
    out.append("")

    for title, x, y, fams in (("H2 — tree vs browser-use, name defects", "tree", "browser_use", (NAME_FAMILY,)),
                              ("H3 — screen-reader vs tree, keyboard/focus defects", "screen_reader", "tree",
                               KEYBOARD_FAMILIES)):
        d = did_table(records, agent_x=x, agent_y=y, families=fams, n_boot=n_boot)
        out += [f"## 4. {title}", ""]
        if not d["tested"]:
            out += [f"**Not tested:** {d['why']} (pre-reg §2 — reported, not dropped).", ""]
            continue
        out += ["| model | defect | tasks | DiD | 95% CI (cluster) | supported |", "|---|---|--:|--:|---|---|"]
        for r in d["rows"]:
            out.append(f"| {r['model']} | {r['defect']} | {r['tasks']} | {_p(r['did'])} | "
                       f"{_p(r['ci'][0])}..{_p(r['ci'][1])} | {'**yes**' if r['supported'] else 'no'} |")
        out.append("")

    out += ["## 5. H4 — tokens per successful task", "",
            "| agent | model | defect | clean tok/win | defect tok/win | ratio | pairs both won | Wilcoxon p |",
            "|---|---|---|--:|--:|--:|--:|--:|"]
    for r in h4_table(records):
        out.append(f"| {r['agent']} | {r['model']} | {r['defect']} | {_n(r['clean_tokens_per_success'], '{:.0f}')} | "
                   f"{_n(r['defect_tokens_per_success'], '{:.0f}')} | {_n(r['ratio'], '{:.2f}')} | "
                   f"{r['pairs_both_won']} | {_n(r['wilcoxon_p'])} |")
    out.append("")

    ex = exclusions(records)
    out += ["## 6. Exclusions", "", "| reason | count |", "|---|--:|"]
    out += [f"| `{k_}` | {v} |" for k_, v in ex.items()] or ["| (none) | 0 |"]
    out.append("")

    out += ["## Cost model (B12.3′)", "",
            "| agent | model | defect | episodes | $ total | $/episode | $/success | × clean | tokens/step | "
            "steps/episode |",
            "|---|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    for r in cost_model(records):
        out.append(f"| {r['agent']} | {r['model']} | {r['defect']} | {r['episodes']} | {_n(r['cost_total'])} | "
                   f"{_n(r['cost_per_episode'])} | {_n(r['cost_per_success'])} | "
                   f"{_n(r['cost_per_success_vs_clean'], '{:.2f}')} | {_n(r['tokens_per_step'], '{:.0f}')} | "
                   f"{_n(r['steps_per_episode'], '{:.1f}')} |")
    out.append("")
    return "\n".join(out)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Pre-registered results-v1 tables from records.jsonl")
    p.add_argument("records", type=Path)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--n-boot", type=int, default=5000)
    args = p.parse_args(argv)
    text = render_markdown(load_records(args.records), n_boot=args.n_boot)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
