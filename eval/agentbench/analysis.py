"""
B11.3′ — the pre-registered analysis (Track B, Week 11).

Every number in `docs/agentbench/results-v1.md` comes from this file, and this
file is committed and tagged with `docs/agentbench/preregistration.md` BEFORE
any Week 12 run (plan v2, rule 2). Changing an analysis after seeing data is a
*deviation*, and the pre-registration says how deviations are reported.

Pure standard library (no numpy/scipy), so it runs anywhere the benchmark
does and gives the same answer on every machine.

Design it implements (see the pre-registration for the reasoning):

- **Paired.** Each defect episode is paired with the clean episode of the same
  (task, agent, provider, model, trial). Both see the same task and seed; only
  the injected defect differs.
- **Primary test:** exact McNemar on the discordant pairs; effect = paired
  difference in success rate (clean − defect) with a Bonett–Price (2012)
  adjusted-Wald interval; Wilson intervals per cell.
- **Multiplicity:** Holm–Bonferroni within each hypothesis family.
- **Clustering:** trials within a task are not independent; every primary
  result is repeated as a sensitivity analysis with a task-level cluster
  bootstrap (seeded, so it is reproducible).
- **Exclusions** are decided by rule, before analysis: any episode with
  `excluded_reason` set, or an evaluator outcome of `indeterminate`, is
  dropped *with its pair*, and counted in every table.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import NormalDist, fmean, pstdev
from typing import Callable, Iterable, Literal, Optional

from pydantic import BaseModel, Field

_N = NormalDist()
CLEAN = "clean"


# --- the record the runner writes (the contract with A12.1′/A12.2′) ----------------

class EpisodeRecord(BaseModel):
    """One agent episode. The runner (Track A) writes these; analysis reads only these."""
    episode_id: str
    task_id: str
    app: str
    defect: str                                  # "clean" or the injector id
    defect_family: Optional[str] = None          # e.g. "name", "keyboard", "contrast"
    agent: str                                   # "tree" | "browser_use" | "screen_reader"
    provider: str
    model: str
    trial: int = Field(ge=0)
    seed: Optional[int] = None
    outcome: Literal["success", "failure", "indeterminate"]   # from evaluators.evaluate
    excluded_reason: Optional[str] = None        # provider_error | budget | injection_unverified | …
    steps: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0)

    @property
    def usable(self) -> bool:
        return self.excluded_reason is None and self.outcome != "indeterminate"

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cache_read_tokens + self.cache_write_tokens


def load_records(path: Path) -> list[EpisodeRecord]:
    """Read episodes from JSON lines."""
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(EpisodeRecord.model_validate(json.loads(line)))
    return out


# --- intervals and tests ------------------------------------------------------------

def wilson(k: int, n: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    """Wilson score interval for k successes in n: (p̂, lower, upper)."""
    if n == 0:
        return (float("nan"), 0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (p, max(0.0, centre - half), min(1.0, centre + half))


def _binom_cdf(k: int, n: int) -> float:
    return sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n


def mcnemar_exact(b: int, c: int) -> float:
    """
    Two-sided exact McNemar p-value: under H0 the b + c discordant pairs split
    Binomial(b + c, 1/2). b = success on clean only, c = success on defect only.
    """
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * _binom_cdf(min(b, c), n))


def paired_diff_ci(a: int, b: int, c: int, d: int, z: float = 1.959963984540054) -> tuple[float, float, float]:
    """
    Paired difference p1 − p2 = (b − c)/n with the Bonett & Price (2012)
    adjusted-Wald interval: add one to each discordant cell, n + 2 in the
    denominator. Good coverage at the small n a benchmark cell has.

    a = success in both, b = clean only, c = defect only, d = neither;
    p1 = clean success rate, p2 = defect success rate.

    (Newcombe's method 10 was the first choice and was rejected while writing
    the tests: with no discordant pairs and p̂ = 0.5 it returns a zero-width
    interval, i.e. claims certainty from 20 pairs.)
    """
    n = a + b + c + d
    if n == 0:
        return (float("nan"), -1.0, 1.0)
    point = (b - c) / n
    p12, p21 = (b + 1) / (n + 2), (c + 1) / (n + 2)
    centre = p12 - p21
    se = math.sqrt(max(0.0, (p12 + p21 - centre * centre) / (n + 2)))
    return (point, max(-1.0, centre - z * se), min(1.0, centre + z * se))


def holm(pvalues: dict[str, float]) -> dict[str, float]:
    """Holm–Bonferroni adjusted p-values (monotone, capped at 1)."""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted: dict[str, float] = {}
    running = 0.0
    for i, (key, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[key] = running
    return adjusted


def mcnemar_pairs_needed(p10: float, p01: float, *, alpha: float = 0.05, power: float = 0.8) -> int:
    """
    Pairs needed to detect a paired difference (Connor 1987), from the pilot's
    discordance: p10 = P(clean success, defect failure), p01 = the reverse.

        n = (z₁₋α/₂·√ψ + z₁₋β·√(ψ − δ²))² / δ²,   ψ = p10 + p01, δ = p10 − p01

    The exact test is slightly conservative relative to this, so the
    pre-registration rounds the result up and adds a margin.
    """
    psi, delta = p10 + p01, p10 - p01
    if delta == 0 or psi <= 0:
        raise ValueError("no planned effect (p10 == p01): a sample size cannot be computed")
    za, zb = _N.inv_cdf(1 - alpha / 2), _N.inv_cdf(power)
    n = (za * math.sqrt(psi) + zb * math.sqrt(max(0.0, psi - delta * delta))) ** 2 / (delta * delta)
    return math.ceil(n)


def wilcoxon_signed_rank(diffs: Iterable[float]) -> dict:
    """
    Two-sided Wilcoxon signed-rank test, normal approximation with tie
    correction; zero differences dropped (Wilcoxon's method). For H4's paired
    token comparison.
    """
    d = [x for x in diffs if x != 0]
    n = len(d)
    if n == 0:
        return {"n": 0, "w_plus": 0.0, "z": 0.0, "p": 1.0}
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    ties = 0.0
    while i < n:
        j = i
        while j + 1 < n and abs(d[order[j + 1]]) == abs(d[order[i]]):
            j += 1
        r = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = r
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    mean = n * (n + 1) / 4
    var = n * (n + 1) * (2 * n + 1) / 24 - ties / 48
    z = (w_plus - mean) / math.sqrt(var) if var > 0 else 0.0
    return {"n": n, "w_plus": w_plus, "z": z, "p": min(1.0, 2 * (1 - _N.cdf(abs(z))))}


def cluster_bootstrap(clusters: dict[str, list], stat: Callable[[list], Optional[float]], *,
                      n_boot: int = 5000, seed: int = 20261108, level: float = 0.95) -> tuple[float, float, float]:
    """
    Percentile bootstrap resampling whole clusters (tasks) with replacement.
    Returns (estimate on the full data, lower, upper). Seeded: reproducible.
    """
    keys = sorted(clusters)
    full = stat([x for k in keys for x in clusters[k]])
    if not keys or full is None:
        return (float("nan"), float("nan"), float("nan"))
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        sample = [x for k in (rng.choice(keys) for _ in keys) for x in clusters[k]]
        s = stat(sample)
        if s is not None:
            stats.append(s)
    stats.sort()
    lo_i = int(((1 - level) / 2) * (len(stats) - 1))
    hi_i = int((1 - (1 - level) / 2) * (len(stats) - 1))
    return (full, stats[lo_i], stats[hi_i])


# --- pairing and effects -------------------------------------------------------------

Pair = tuple[str, bool, bool]    # (task_id, clean success, defect success)


def _key(r: EpisodeRecord) -> tuple:
    return (r.task_id, r.agent, r.provider, r.model, r.trial)


def pair_episodes(records: list[EpisodeRecord], *, defect: str, agent: str, model: str) -> tuple[list[Pair], int]:
    """
    Pairs (clean, defect) for one agent × model × defect. Returns (pairs,
    pairs dropped by the exclusion rules). A pair is usable only if BOTH halves
    are; dropping one half alone would bias the comparison.
    """
    clean = {_key(r): r for r in records if r.defect == CLEAN and r.agent == agent and r.model == model}
    pairs: list[Pair] = []
    dropped = 0
    for r in records:
        if r.defect != defect or r.agent != agent or r.model != model:
            continue
        c = clean.get(_key(r))
        if c is None:
            dropped += 1
            continue
        if not (c.usable and r.usable):
            dropped += 1
            continue
        pairs.append((r.task_id, c.outcome == "success", r.outcome == "success"))
    return pairs, dropped


def _table(pairs: list[Pair]) -> tuple[int, int, int, int]:
    a = sum(1 for _, x, y in pairs if x and y)
    b = sum(1 for _, x, y in pairs if x and not y)
    c = sum(1 for _, x, y in pairs if not x and y)
    d = sum(1 for _, x, y in pairs if not x and not y)
    return a, b, c, d


def _diff(pairs: list[Pair]) -> Optional[float]:
    if not pairs:
        return None
    return sum(x for _, x, _ in pairs) / len(pairs) - sum(y for _, _, y in pairs) / len(pairs)


def paired_effect(pairs: list[Pair], dropped: int = 0, *, n_boot: int = 5000, seed: int = 20261108) -> dict:
    """The primary result for one comparison: everything results-v1 reports."""
    a, b, c, d = _table(pairs)
    n = a + b + c + d
    diff, lo, hi = paired_diff_ci(a, b, c, d)
    by_task: dict[str, list] = defaultdict(list)
    for p in pairs:
        by_task[p[0]].append(p)
    _, blo, bhi = cluster_bootstrap(by_task, _diff, n_boot=n_boot, seed=seed)
    return {
        "pairs": n, "dropped": dropped, "tasks": len(by_task),
        "a_both": a, "b_clean_only": b, "c_defect_only": c, "d_neither": d,
        "clean_success": wilson(a + b, n), "defect_success": wilson(a + c, n),
        "diff": diff, "diff_ci": (lo, hi), "diff_ci_cluster_bootstrap": (blo, bhi),
        "mcnemar_p": mcnemar_exact(b, c),
    }


def difference_in_differences(pairs_x: list[Pair], pairs_y: list[Pair], *, n_boot: int = 5000,
                              seed: int = 20261108) -> dict:
    """
    H2/H3: is the defect's effect on agent X larger than on agent Y? Effect =
    (clean − defect) success; DiD = effect_X − effect_Y, cluster-bootstrapped
    over tasks the two share.
    """
    tasks = sorted({t for t, _, _ in pairs_x} & {t for t, _, _ in pairs_y})
    clusters = {t: [("x", p) for p in pairs_x if p[0] == t] + [("y", p) for p in pairs_y if p[0] == t]
                for t in tasks}

    def did(sample: list) -> Optional[float]:
        dx = _diff([p for g, p in sample if g == "x"])
        dy = _diff([p for g, p in sample if g == "y"])
        return None if dx is None or dy is None else dx - dy

    est, lo, hi = cluster_bootstrap(clusters, did, n_boot=n_boot, seed=seed)
    return {"tasks": len(tasks), "did": est, "ci": (lo, hi)}


def tokens_per_success(records: list[EpisodeRecord]) -> Optional[float]:
    """H4's metric: all tokens spent ÷ successful tasks (failures cost tokens too)."""
    usable = [r for r in records if r.usable]
    wins = sum(1 for r in usable if r.outcome == "success")
    return None if wins == 0 else sum(r.tokens for r in usable) / wins


# --- the pilot: what Week 12 is sized from (W10 gate) -----------------------------------

def pilot_summary(records: list[EpisodeRecord], *, alpha: float = 0.05, power: float = 0.8,
                  margin: float = 1.2) -> dict:
    """
    Per (agent, model, defect) cell: episodes, success with Wilson interval,
    tokens and cost per episode (mean, sd). Per defect vs clean: observed
    discordance and the pairs Week 12 needs to detect an effect that size.
    """
    cells: dict[tuple, list[EpisodeRecord]] = defaultdict(list)
    for r in records:
        cells[(r.agent, r.model, r.defect)].append(r)
    table = []
    for (agent, model, defect), rs in sorted(cells.items()):
        usable = [r for r in rs if r.usable]
        k = sum(1 for r in usable if r.outcome == "success")
        toks = [float(r.tokens) for r in usable]
        costs = [r.cost_usd for r in rs]
        table.append({
            "agent": agent, "model": model, "defect": defect,
            "episodes": len(rs), "excluded": len(rs) - len(usable),
            "success": wilson(k, len(usable)),
            "success_var": (k / len(usable)) * (1 - k / len(usable)) if usable else None,
            "tokens_mean": fmean(toks) if toks else None, "tokens_sd": pstdev(toks) if len(toks) > 1 else None,
            "cost_mean": fmean(costs) if costs else None, "cost_total": sum(costs),
        })
    sizing = []
    for agent, model in sorted({(r.agent, r.model) for r in records}):
        for defect in sorted({r.defect for r in records if r.defect != CLEAN}):
            pairs, _ = pair_episodes(records, defect=defect, agent=agent, model=model)
            if not pairs:
                continue
            _, b, c, _ = _table(pairs)
            p10, p01 = b / len(pairs), c / len(pairs)
            try:
                needed = math.ceil(mcnemar_pairs_needed(p10, p01, alpha=alpha, power=power) * margin)
            except ValueError:
                needed = None
            sizing.append({"agent": agent, "model": model, "defect": defect, "pilot_pairs": len(pairs),
                           "p10": p10, "p01": p01, "pairs_needed": needed})
    return {"cells": table, "sizing": sizing,
            "cost_total": sum(r.cost_usd for r in records),
            "tokens_per_episode": fmean([float(r.tokens) for r in records]) if records else None}
