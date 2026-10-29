"""
A14.2′ — agent-check reports: SARIF, JSON, and an HTML trace.

The point is reuse, not new report code. An agent-check failure is a
`Finding` like any other, so it flows through:

- **SARIF** — the existing `verity.report.sarif.write_sarif`, which already maps
  `needs-review` → SARIF `note` and `authoritative` → `error`. So an unconfirmed
  agent failure annotates a PR without failing the build, and a confirmed one
  (once B14.1′ is wired) gates — no agent-check-specific SARIF logic.
- **JSON** — the `AuditReport` serialised, the same shape `verity scan` emits.
- **HTML trace** — the Week-12 `trace_viewer.render_html`, replaying every step
  with the accessibility tree the agent saw, so a reviewer reads *why* the agent
  failed, not just that it did.

The `AuditReport` is the GitHub Action input: the Action (A8.1) already consumes
the SARIF this writes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from verity.agent_check.check import AgentCheckResult
from verity.models.schemas import AuditReport


def build_audit_report(result: AgentCheckResult) -> AuditReport:
    """Wrap the check's findings in the same AuditReport `verity scan` produces,
    so every downstream report path works unchanged."""
    from verity.orchestrator.main import build_conformance_map

    return AuditReport(
        target=result.url,
        standard="WCAG2.2-AA",
        findings=result.findings,
        conformance=build_conformance_map(result.findings),
        verity_version="0.1.0",
        ruleset_version="1.0.0",
    )


def build_trace(result: AgentCheckResult) -> dict:
    """The replayable trace for `trace_viewer.render_html`: the task as the goal,
    and every step's accessibility tree + action."""
    ep = result.episode
    steps = getattr(ep, "steps", []) if ep else []
    return {
        "episode_id": f"agent-check:{result.url}",
        "task_id": result.url,
        "agent": "agent-check",
        "model_label": "",
        "defect": None,
        "trial": 0,
        "goal": result.task,
        "done": getattr(ep, "done", False) if ep else False,
        "reward": 1.0 if result.succeeded else 0.0,
        "seconds": getattr(ep, "seconds", 0.0) if ep else 0.0,
        "infeasible": result.verdict == "infeasible",
        "parse_failures": 0,
        "steps": [
            {"n": i + 1, "observation": s.observation, "action": s.action,
             "ok": s.ok, "error": s.error}
            for i, s in enumerate(steps)
        ],
    }


def write_reports(
    result: AgentCheckResult,
    *,
    json_path: Optional[str] = None,
    sarif_path: Optional[str] = None,
    html_path: Optional[str] = None,
    policy=None,
) -> dict:
    """Write whichever reports were requested; return the paths written."""
    report = build_audit_report(result)
    written: dict[str, Path] = {}

    if json_path:
        p = Path(json_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        written["json"] = p

    if sarif_path:
        from verity.report.policy import CiPolicy
        from verity.report.sarif import write_sarif

        # Agent-check findings are needs-review by default (until B14.1′ confirms
        # them). The default scan policy only annotates `ai_assisted` and above,
        # which would hide every agent-check finding from SARIF — defeating the
        # purpose of --sarif. So agent-check annotates needs-review (as SARIF
        # `note`s that never gate), while a caller's policy can still widen it.
        written["sarif"] = write_sarif(report, sarif_path,
                                       policy=policy or CiPolicy(annotate_on="everything"))

    if html_path:
        from eval.agentbench.trace_viewer import render_html

        p = Path(html_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_html(build_trace(result)), encoding="utf-8")
        written["html"] = p

    return written
