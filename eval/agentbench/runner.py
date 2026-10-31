"""
A12.1′ — the benchmark runner.

Week 10's pilot sized the study; this runs it. The runner's whole job is to turn
the pre-registered design into `EpisodeRecord`s (the contract `analysis.py`
reads) **without ever letting the operator's choices contaminate the result** —
which is why it does four specific things and refuses to do a fifth:

1. **Deterministic, pre-registered order.** The plan (task × defect × agent ×
   model × trial) is enumerated deterministically, then shuffled *once* with the
   pre-registration's seed (`ORDER_SEED`) and recorded. Running conditions in a
   fixed, seeded order means time-of-day and provider drift cannot line up with
   a condition — the pre-registration, §3 "Order", requires this.

2. **Resumable and idempotent.** Every episode has a stable `episode_id`. The
   records file *is* the manifest: on resume, episodes already written are
   skipped, and the ledger re-reads its spend from disk, so a run that stops
   (crash, budget, Ctrl-C) continues from where it stopped instead of
   double-counting or granting itself a fresh budget.

3. **A hard budget cap.** Spend is enforced by the `CostLedger` *before* each
   model call (worst case per call). With one worker the cap is exact. With N
   workers each gets a ledger capped at `cap/N`, so the sum still cannot exceed
   the cap — the budget never overspends, at the documented cost that a cheap
   shard cannot lend its slack to an expensive one.

4. **Injection verified before measurement.** A defect episode is run only after
   `verify_injection.verify` confirms the variant carries *exactly* the intended
   defect and is pixel-identical to clean (A11.2′). A variant that fails
   verification is recorded `injection_unverified` and skipped — the pre-reg
   says such a pair never runs.

And the fifth, which it refuses: **it never computes success by condition during
the run.** "No peeking" (pre-reg §9) is a property of the code, not a promise —
the runner tracks only error rate and spend while running; success rates come
from `analysis.py`, after the run is complete, from the records on disk.

Everything is injectable (env, agent, provider, the injection verifier) so the
whole orchestration is tested with fakes — no browser, no network, no spend.
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

from eval.agentbench.agents.browser_use_agent import BrowserUseAgent
from eval.agentbench.agents.tree_agent import TreeAgent, TreeAgentResult
from eval.agentbench.analysis import EpisodeRecord
from eval.agentbench.attacks import ATTACKS, Attack, HijackRecord, assess_hijack
from eval.agentbench.agents.screen_reader_agent import ScreenReaderAgent
from eval.agentbench.env import MiniWoBEnv
from eval.agentbench.hardening import HARDENED_AGENTS, base_agent
from eval.agentbench.loop_guard import LoopGuard
from eval.agentbench.providers import BudgetExceeded, CostLedger, make_provider
from eval.agentbench.providers.base import BaseProvider, ProviderError
from eval.agentbench.tasks import MINIWOB_TASKS, Task, cells
from eval.agentbench.verify_injection import VerifyResult, verify

# The agents the runner can build by name: the three subjects, plus each one
# hardened against prompt injection (B13.2′, measured on the attack track).
AGENTS = {"tree": TreeAgent, "browser_use": BrowserUseAgent, "screen_reader": ScreenReaderAgent,
          **HARDENED_AGENTS}

# The one seed the pre-registration fixes for run order (and the bootstrap).
# Hard-coded here, not a parameter, so a run cannot quietly reorder itself.
ORDER_SEED = 20261108
CLEAN = "clean"

# Defect id -> WCAG defect family, for the analysis tables (pre-reg §4): the
# name family and the keyboard/focus family (H3).
DEFECT_FAMILY = {"strip_name": "name", "div_button": "name", "detach_label": "name",
                 "keyboard_trap": "keyboard", "remove_from_tab_order": "keyboard", "outline_none": "focus"}

# MiniWoB's raw reward is time-discounted into (0, 1] on a solve and <= 0
# otherwise, so the operational env-reward evaluator for MiniWoB counts any
# positive reward as success. (A vendored app would carry its own `success:`
# evaluator instead; this is the MiniWoB rule, stated so it is not a magic
# constant.)
SUCCESS_MIN = 1e-9


@dataclass(frozen=True)
class EpisodeSpec:
    """One planned episode. `episode_id` is stable across runs — it is the key
    resume and idempotency are built on."""

    episode_id: str
    task: Task
    agent: str
    model_label: str
    model_spec: str
    trial: int
    defect: Optional[str]  # None == the clean control


def _episode_id(agent: str, model_label: str, task_id: str, defect: Optional[str], trial: int) -> str:
    return f"{agent}|{model_label}|{task_id}|{defect or CLEAN}|t{trial}"


def _safe_name(episode_id: str) -> str:
    """A filesystem-safe trace filename for an episode id."""
    return re.sub(r"[^0-9A-Za-z._-]+", "_", episode_id)


def build_plan(
    models: dict[str, str],
    *,
    tasks: tuple[Task, ...] = MINIWOB_TASKS,
    agents: tuple[str, ...] = ("tree",),
    trials: int = 1,
) -> list[EpisodeSpec]:
    """
    Enumerate the full (task × {clean + defect} × agent × model × trial) matrix.

    `models` maps a label ("frontier", "local-a", …) to a provider spec
    ("anthropic:claude-sonnet-5-5", "ollama:qwen3:8b"). The clean control is
    emitted once per task (it is the same page for every defect), via
    `tasks.cells`.
    """
    plan: list[EpisodeSpec] = []
    for agent in agents:
        for label, spec in models.items():
            for trial in range(trials):
                for task, defect in cells(tasks):
                    eid = _episode_id(agent, label, task.id, defect, trial)
                    plan.append(EpisodeSpec(eid, task, agent, label, spec, trial, defect))
    return plan


def order_plan(plan: list[EpisodeSpec], *, seed: int = ORDER_SEED) -> list[EpisodeSpec]:
    """
    Shuffle the plan once, deterministically. Sorted by episode_id first so the
    input order (dict iteration, enumeration) cannot leak into the result — the
    same set of episodes always yields the same run order for a given seed.
    """
    import random

    ordered = sorted(plan, key=lambda e: e.episode_id)
    random.Random(seed).shuffle(ordered)
    return ordered


def shard(plan: list[EpisodeSpec], workers: int) -> list[list[EpisodeSpec]]:
    """Round-robin partition, so each worker's shard spans the whole run order
    (not one contiguous block) — a worker that dies takes a representative
    slice with it, not an entire model or task."""
    if workers < 1:
        raise ValueError("workers must be >= 1")
    shards: list[list[EpisodeSpec]] = [[] for _ in range(workers)]
    for i, spec in enumerate(plan):
        shards[i % workers].append(spec)
    return [s for s in shards if s]


# -- outcome & records --------------------------------------------------------

def outcome_from_reward(done: bool, reward: float) -> str:
    """The MiniWoB env-reward evaluator: a positive reward is a solve."""
    return "success" if reward > SUCCESS_MIN else "failure"


def _record_from_result(spec: EpisodeSpec, result: TreeAgentResult) -> EpisodeRecord:
    ep = result.episode
    outcome = outcome_from_reward(ep.done, ep.reward)
    # An agent that honestly reported the task infeasible did not succeed; it is
    # a failure of the task, not an excluded error — the defect making the task
    # impossible is exactly the effect the benchmark measures.
    return EpisodeRecord(
        episode_id=spec.episode_id,
        task_id=spec.task.id,
        app=spec.task.app,
        defect=spec.defect or CLEAN,
        defect_family=DEFECT_FAMILY.get(spec.defect or "") or (None if spec.defect is None else "other"),
        agent=spec.agent,
        provider=result.provider,
        model=spec.model_label,
        trial=spec.trial,
        seed=spec.trial,  # the trial index fixes the seed (pre-reg §3)
        outcome=outcome,
        steps=result.steps_used,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cache_read_tokens=result.cache_read_tokens,
        cache_write_tokens=result.cache_write_tokens,
        cost_usd=result.cost_usd,
    )


def _excluded_record(spec: EpisodeSpec, provider_name: str, reason: str) -> EpisodeRecord:
    """A record for an episode that could not be measured. `outcome` is set to
    `failure` only to satisfy the type; `excluded_reason` is what analysis keys
    on, and it drops the pair before any rate is computed."""
    return EpisodeRecord(
        episode_id=spec.episode_id, task_id=spec.task.id, app=spec.task.app,
        defect=spec.defect or CLEAN,
        defect_family=DEFECT_FAMILY.get(spec.defect or "") or (None if spec.defect is None else "other"),
        agent=spec.agent, provider=provider_name, model=spec.model_label,
        trial=spec.trial, seed=spec.trial, outcome="failure", excluded_reason=reason,
    )


def _trace_from_result(spec: EpisodeSpec, result: TreeAgentResult) -> dict:
    """The full, replayable trace A12.3′ reads: the goal and every step's
    observation / action / result."""
    ep = result.episode
    return {
        "episode_id": spec.episode_id,
        "task_id": spec.task.id,
        "agent": spec.agent,
        "model_label": spec.model_label,
        "provider": result.provider,
        "model": result.model,
        "defect": spec.defect or CLEAN,
        "trial": spec.trial,
        "goal": ep.goal,
        "done": ep.done,
        "reward": ep.reward,
        "seconds": ep.seconds,
        "infeasible": result.infeasible,
        "parse_failures": result.parse_failures,
        "steps": [
            {"n": i + 1, "observation": s.observation, "action": s.action,
             "ok": s.ok, "error": s.error}
            for i, s in enumerate(ep.steps)
        ],
    }


# -- the run report (monitoring only — never success by condition) ------------

@dataclass
class RunReport:
    """What the operator may see *during and after* the run: counts and spend,
    not success rates. Computing success by condition is `analysis.py`'s job,
    after the run — see "no peeking" (pre-reg §9)."""

    planned: int = 0
    already_done: int = 0
    run: int = 0
    excluded: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    budget_stopped: bool = False
    order_seed: int = ORDER_SEED

    def _note_exclusion(self, reason: str) -> None:
        self.excluded[reason] = self.excluded.get(reason, 0) + 1


# -- the runner ---------------------------------------------------------------

def _completed_ids(records_path: Path) -> set[str]:
    """Episode ids already written — the resume manifest, read from the records
    file itself so there is no second source of truth to fall out of sync."""
    done: set[str] = set()
    if records_path.exists():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["episode_id"])
    return done


def _default_provider_factory(label: str, spec: str, ledger: CostLedger) -> BaseProvider:
    return make_provider(spec, ledger=ledger)


def _default_agent_factory(name: str, provider: BaseProvider, *, max_steps: int):
    """Build the agent for `name`, each with a fresh per-episode loop guard."""
    cls = AGENTS.get(name)
    if cls is None:
        raise ValueError(f"unknown agent {name!r}; known: {', '.join(sorted(AGENTS))}")
    return cls(provider, max_steps=max_steps, loop_guard=LoopGuard())


def run_benchmark(
    models: dict[str, str],
    *,
    out_dir: Path,
    tasks: tuple[Task, ...] = MINIWOB_TASKS,
    agents: tuple[str, ...] = ("tree",),
    trials: int = 1,
    cap_usd: Optional[float] = None,
    workers: int = 1,
    resume: bool = True,
    max_steps: int = 15,
    headless: bool = True,
    env_factory: Callable[..., MiniWoBEnv] = MiniWoBEnv,
    agent_factory: Callable[[str, BaseProvider], object] = None,
    provider_factory: Callable[[str, str, CostLedger], BaseProvider] = _default_provider_factory,
    verify_fn: Callable[..., VerifyResult] = verify,
) -> RunReport:
    """
    Run the whole benchmark into `out_dir`, resumably.

    Writes `out_dir/records.jsonl` (the analysis contract) and one
    `out_dir/traces/<episode>.json` per measured episode. Returns a `RunReport`
    of counts and spend. Only `agents=("tree",)` is runnable today; the
    browser-use and screen-reader agents (Week 13) slot in through
    `agent_factory` when they exist.
    """
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    records_path = out_dir / "records.jsonl"
    if agent_factory is None:
        agent_factory = lambda name, p: _default_agent_factory(name, p, max_steps=max_steps)

    plan = order_plan(build_plan(models, tasks=tasks, agents=agents, trials=trials))
    done_ids = _completed_ids(records_path) if resume else set()
    todo = [s for s in plan if s.episode_id not in done_ids]

    report = RunReport(planned=len(plan), already_done=len(plan) - len(todo))
    if not todo:
        report.cost_usd = _ledger_total(out_dir, workers if workers > 1 else 1)
        return report

    shards = shard(todo, workers)
    n_shards = len(shards)
    shard_cap = (cap_usd / n_shards) if (cap_usd is not None and n_shards) else cap_usd

    write_lock = threading.Lock()
    stop = threading.Event()  # a budget stop in any shard halts the whole run

    def write_record(rec: EpisodeRecord) -> None:
        with write_lock:
            with records_path.open("a", encoding="utf-8") as f:
                f.write(rec.model_dump_json() + "\n")

    def write_trace(spec: EpisodeSpec, trace: dict) -> None:
        (out_dir / "traces" / f"{_safe_name(spec.episode_id)}.json").write_text(
            json.dumps(trace, indent=2), encoding="utf-8")

    def run_shard(idx: int, specs: list[EpisodeSpec]) -> tuple[int, dict[str, int], float, bool]:
        ledger_path = out_dir / (f"ledger.shard{idx}.jsonl" if n_shards > 1 else "ledger.jsonl")
        ledger = CostLedger(cap_usd=shard_cap, path=ledger_path)
        providers: dict[str, BaseProvider] = {}
        ran = 0
        excl: dict[str, int] = {}
        budget_stopped = False

        def provider_for(spec: EpisodeSpec) -> BaseProvider:
            if spec.model_label not in providers:
                providers[spec.model_label] = provider_factory(spec.model_label, spec.model_spec, ledger)
            return providers[spec.model_label]

        with env_factory(headless=headless) as env:
            for spec in specs:
                if stop.is_set():
                    break
                provider = provider_for(spec)

                # Gate: a defect variant must verify before it is measured.
                if spec.defect is not None:
                    try:
                        v = verify_fn(env, spec.task.id, spec.trial, spec.defect)
                    except Exception as exc:  # a verification failure is not a task failure
                        write_record(_excluded_record(spec, provider.name, "injection_unverified"))
                        excl["injection_unverified"] = excl.get("injection_unverified", 0) + 1
                        continue
                    if not v.ok:
                        write_record(_excluded_record(spec, provider.name, "injection_unverified"))
                        excl["injection_unverified"] = excl.get("injection_unverified", 0) + 1
                        continue

                try:
                    result = agent_factory(spec.agent, provider).run(
                        env, spec.task.id, seed=spec.trial, defect=spec.defect)
                except BudgetExceeded:
                    # The cap refused a call. Record this episode as excluded and
                    # stop the run — never overspend to finish it.
                    write_record(_excluded_record(spec, provider.name, "budget"))
                    excl["budget"] = excl.get("budget", 0) + 1
                    budget_stopped = True
                    stop.set()
                    break
                except ProviderError:
                    write_record(_excluded_record(spec, provider.name, "provider_error"))
                    excl["provider_error"] = excl.get("provider_error", 0) + 1
                    continue

                write_trace(spec, _trace_from_result(spec, result))
                write_record(_record_from_result(spec, result))
                ran += 1

        return ran, excl, ledger.total_usd, budget_stopped

    if n_shards == 1:
        ran, excl, cost, stopped = run_shard(0, shards[0])
        results = [(ran, excl, cost, stopped)]
    else:
        with ThreadPoolExecutor(max_workers=n_shards) as pool:
            results = list(pool.map(lambda a: run_shard(*a), enumerate(shards)))

    for ran, excl, cost, stopped in results:
        report.run += ran
        report.cost_usd += cost
        report.budget_stopped = report.budget_stopped or stopped
        for reason, k in excl.items():
            for _ in range(k):
                report._note_exclusion(reason)
    return report


def _ledger_total(out_dir: Path, n_shards: int) -> float:
    total = 0.0
    for p in sorted(out_dir.glob("ledger*.jsonl")):
        total += CostLedger(path=p).total_usd
    return total


# -- the injection-attack track (A13.2′) --------------------------------------

@dataclass(frozen=True)
class AttackSpec:
    episode_id: str
    task: Task
    agent: str
    model_label: str
    model_spec: str
    trial: int
    attack: Attack


def build_attack_plan(
    models: dict[str, str],
    *,
    tasks: tuple[Task, ...] = MINIWOB_TASKS,
    agents: tuple[str, ...] = ("tree",),
    attacks: tuple[Attack, ...] = ATTACKS,
    trials: int = 1,
) -> list[AttackSpec]:
    """Enumerate (task × attack × agent × model × trial). Every agent is run
    against every attack — including attacks it cannot perceive — so the hijack
    table shows the contrast (a vision agent's 0% on an aria-only injection is a
    result, not a gap)."""
    plan: list[AttackSpec] = []
    for agent in agents:
        for label, spec in models.items():
            for trial in range(trials):
                for task in tasks:
                    for attack in attacks:
                        eid = f"{agent}|{label}|{task.id}|attack:{attack.id}|t{trial}"
                        plan.append(AttackSpec(eid, task, agent, label, spec, trial, attack))
    return plan


def run_attack_track(
    models: dict[str, str],
    *,
    out_dir: Path,
    tasks: tuple[Task, ...] = MINIWOB_TASKS,
    agents: tuple[str, ...] = ("tree",),
    attacks: tuple[Attack, ...] = ATTACKS,
    trials: int = 1,
    cap_usd: Optional[float] = None,
    resume: bool = True,
    max_steps: int = 15,
    headless: bool = True,
    env_factory: Callable[..., MiniWoBEnv] = MiniWoBEnv,
    agent_factory: Callable[[str, BaseProvider], object] = None,
    provider_factory: Callable[[str, str, CostLedger], BaseProvider] = _default_provider_factory,
) -> RunReport:
    """
    Run the injection-attack track into `out_dir/hijacks.jsonl` (+ traces),
    resumably and under a budget cap. Attacks run on the **clean** page, so a
    behaviour change is attributable to the injected text. Hijack scoring is the
    deterministic canary check (`attacks.assess_hijack`) — no model judges it.
    """
    out_dir = Path(out_dir)
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    hijacks_path = out_dir / "hijacks.jsonl"
    if agent_factory is None:
        agent_factory = lambda name, p: _default_agent_factory(name, p, max_steps=max_steps)

    plan = order_plan_attacks(build_attack_plan(models, tasks=tasks, agents=agents, attacks=attacks, trials=trials))
    done_ids = _completed_ids(hijacks_path) if resume else set()
    todo = [s for s in plan if s.episode_id not in done_ids]

    report = RunReport(planned=len(plan), already_done=len(plan) - len(todo))
    if not todo:
        return report

    ledger = CostLedger(cap_usd=cap_usd, path=out_dir / "attack-ledger.jsonl")
    providers: dict[str, BaseProvider] = {}

    def provider_for(spec: AttackSpec) -> BaseProvider:
        if spec.model_label not in providers:
            providers[spec.model_label] = provider_factory(spec.model_label, spec.model_spec, ledger)
        return providers[spec.model_label]

    with env_factory(headless=headless) as env:
        for spec in todo:
            provider = provider_for(spec)
            agent = agent_factory(spec.agent, provider)
            try:
                result = agent.run(env, spec.task.id, seed=spec.trial, defect=None, attack=spec.attack.id)
            except BudgetExceeded:
                report._note_exclusion("budget")
                report.budget_stopped = True
                break
            except ProviderError:
                _write_hijack(hijacks_path, _excluded_hijack(spec, provider.name))
                report._note_exclusion("provider_error")
                continue

            assessment = assess_hijack(result.episode)
            rec = HijackRecord(
                episode_id=spec.episode_id, task_id=spec.task.id, agent=spec.agent,
                provider=result.provider, model=spec.model_label, attack=spec.attack.id,
                vector=spec.attack.vector, trial=spec.trial,
                perceivable=base_agent(spec.agent) in spec.attack.perceivable_by,
                hijacked=assessment.hijacked, attempted=assessment.attempted,
                task_outcome=outcome_from_reward(result.episode.done, result.episode.reward),
            )
            _write_hijack(hijacks_path, rec)
            (out_dir / "traces" / f"{_safe_name(spec.episode_id)}.json").write_text(
                json.dumps({**_trace_from_result(_as_episode_spec(spec), result),
                            "attack": spec.attack.id, "vector": spec.attack.vector,
                            "hijacked": assessment.hijacked}, indent=2), encoding="utf-8")
            report.run += 1

    report.cost_usd = ledger.total_usd
    return report


def order_plan_attacks(plan: list[AttackSpec], *, seed: int = ORDER_SEED) -> list[AttackSpec]:
    import random

    ordered = sorted(plan, key=lambda e: e.episode_id)
    random.Random(seed).shuffle(ordered)
    return ordered


def _as_episode_spec(spec: AttackSpec) -> EpisodeSpec:
    """Adapt an AttackSpec to the EpisodeSpec shape the trace writer expects."""
    return EpisodeSpec(spec.episode_id, spec.task, spec.agent, spec.model_label,
                       spec.model_spec, spec.trial, defect=None)


def _write_hijack(path: Path, rec: HijackRecord) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(rec.model_dump_json() + "\n")


def _excluded_hijack(spec: AttackSpec, provider_name: str) -> HijackRecord:
    return HijackRecord(
        episode_id=spec.episode_id, task_id=spec.task.id, agent=spec.agent,
        provider=provider_name, model=spec.model_label, attack=spec.attack.id,
        vector=spec.attack.vector, trial=spec.trial,
        perceivable=base_agent(spec.agent) in spec.attack.perceivable_by,
        hijacked=False, task_outcome="failure", excluded_reason="provider_error",
    )
