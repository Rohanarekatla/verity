"""
B14.2′ — the agent-readiness score (Track B, Week 14).

"Is this page ready for AI agents?" — as a number with **evidence for every
point**, never a vibe. Two halves:

**Static** — from one render's accessibility tree (the interface tree-based
agents use: Playwright MCP, ChatGPT Atlas) plus Verity's findings and Rohan's
WebMCP readiness (A16.1′):

| Point | Max | Earned from |
|---|--:|---|
| `named_controls` | 30 | share of rendered controls with a computed accessible name — an unnamed control is unaddressable for a tree agent |
| `structure` | 15 | a page title (5), a `main` landmark (5), at least one heading (5) |
| `well_formed` | 15 | no focusable node the tree hides (focus lands somewhere the agent cannot see) |
| `stability` | 10 | the controls (role + name) are identical across two renders — an agent's plan survives a reload |
| `wcag_blockers` | 10 | no authoritative failure on the criteria agents trip on (4.1.2, 1.3.1, 2.1.1, 2.1.2, 2.4.3), −2 each |
| `webmcp` | 20 | WebMCP readiness score (forms an agent can drive by declared tools) |

**Dynamic** — real agent tasks (`verity agent-check`): the share completed.

Honesty rules, same as the rest of Verity:

- a point that was **not measured** (no second render, no WebMCP extraction,
  no tasks) is reported as such and excluded from the denominator — never
  counted as earned. `coverage` says what fraction of the possible points the
  score is based on;
- a dynamic failure only counts **against the site** when agent-check
  confirmed it (B14.1′); unconfirmed failures are listed as needs-review;
- every point carries the evidence that earned or lost it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal, Optional

from verity.agents.announce import CONTROL_ROLES
from verity.agents.virtual_sr import AxTree, _iter_all

Status = Literal["measured", "not_measured"]

AGENT_BLOCKING_SC = frozenset({"4.1.2", "1.3.1", "2.1.1", "2.1.2", "2.4.3"})
EVIDENCE_LIMIT = 5


@dataclass
class ReadinessPoint:
    id: str
    label: str
    max: float
    earned: float = 0.0
    status: Status = "measured"
    evidence: list[str] = field(default_factory=list)


@dataclass
class TaskOutcome:
    """One agent-check run, summarised for scoring."""
    task: str
    succeeded: bool
    confirmed_failure: bool = False   # B14.1′ confirmed a site defect


@dataclass
class ReadinessReport:
    points: list[ReadinessPoint]
    static_score: Optional[float]           # 0–100 over measured static points
    static_coverage: float                  # share of static points measured
    dynamic_score: Optional[float]          # 0–100 share of tasks completed
    tasks: list[TaskOutcome] = field(default_factory=list)
    overall: Optional[float] = None
    notes: list[str] = field(default_factory=list)


def _controls(tree: AxTree):
    return [n for n in _iter_all(tree) if not n.ignored and n.role in CONTROL_ROLES]


def _signature(tree: AxTree) -> list[tuple[str, str]]:
    return [(n.role or "", (n.name or "").strip()) for n in _controls(tree)]


def static_points(
    tree: AxTree,
    *,
    findings: Optional[Iterable] = None,
    second_tree: Optional[AxTree] = None,
    webmcp_report=None,
) -> list[ReadinessPoint]:
    points: list[ReadinessPoint] = []

    # named_controls
    controls = _controls(tree)
    p = ReadinessPoint("named_controls", "controls have accessible names", 30)
    if not controls:
        p.status, p.evidence = "not_measured", ["no rendered controls on the page"]
    else:
        unnamed = [n for n in controls if not (n.name or "").strip()]
        p.earned = 30 * (len(controls) - len(unnamed)) / len(controls)
        p.evidence = [f"{len(controls) - len(unnamed)}/{len(controls)} controls named"] + [
            f"unnamed {n.role} (ax node {n.node_id})" for n in unnamed[:EVIDENCE_LIMIT]]
    points.append(p)

    # structure
    nodes = [n for n in _iter_all(tree) if not n.ignored]
    root = tree.nodes.get(tree.root_id) if tree.root_id else None
    title = bool(root and (root.name or "").strip())
    main = any(n.role == "main" for n in nodes)
    heading = any(n.role == "heading" for n in nodes)
    p = ReadinessPoint("structure", "page title, main landmark, headings", 15,
                       earned=5 * title + 5 * main + 5 * heading)
    p.evidence = [f"title: {'yes' if title else 'missing'}", f"main landmark: {'yes' if main else 'missing'}",
                  f"headings: {'yes' if heading else 'none'}"]
    points.append(p)

    # well_formed: focusable nodes the tree hides
    hidden_focusable = [n for n in _iter_all(tree) if n.ignored and n.focusable]
    p = ReadinessPoint("well_formed", "no focusable element hidden from the tree", 15)
    p.earned = 15.0 if not hidden_focusable else max(0.0, 15.0 - 3 * len(hidden_focusable))
    p.evidence = ["no hidden focusable nodes"] if not hidden_focusable else [
        f"{len(hidden_focusable)} focusable node(s) hidden from the accessibility tree"] + [
        f"ax node {n.node_id} ({n.role})" for n in hidden_focusable[:EVIDENCE_LIMIT]]
    points.append(p)

    # stability
    p = ReadinessPoint("stability", "controls identical across two renders", 10)
    if second_tree is None:
        p.status, p.evidence = "not_measured", ["only one render was taken"]
    else:
        a, b = _signature(tree), _signature(second_tree)
        same = sum(1 for x, y in zip(a, b) if x == y)
        denom = max(len(a), len(b)) or 1
        p.earned = 10 * same / denom
        p.evidence = [f"{same}/{denom} controls identical (role + name, in order)"]
    points.append(p)

    # wcag_blockers
    p = ReadinessPoint("wcag_blockers", "no authoritative failures agents trip on", 10)
    if findings is None:
        p.status, p.evidence = "not_measured", ["no scan findings were supplied"]
    else:
        blockers = [f for f in findings if getattr(f.sc, "id", None) in AGENT_BLOCKING_SC
                    and f.outcome == "fail" and getattr(f.provenance, "value", f.provenance) == "authoritative"
                    and not getattr(f, "waived", False)]
        p.earned = max(0.0, 10.0 - 2 * len(blockers))
        p.evidence = [f"{len(blockers)} authoritative failure(s) on {', '.join(sorted(AGENT_BLOCKING_SC))}"] + [
            f"SC {f.sc.id} {f.rule_id} at {f.evidence.dom_selector}" for f in blockers[:EVIDENCE_LIMIT]]
    points.append(p)

    # webmcp
    p = ReadinessPoint("webmcp", "forms drivable through declared WebMCP tools", 20)
    if webmcp_report is None:
        p.status, p.evidence = "not_measured", ["WebMCP readiness was not checked"]
    else:
        score = float(getattr(webmcp_report, "score", 0.0))
        p.earned = 20 * max(0.0, min(100.0, score)) / 100
        uncovered = list(getattr(webmcp_report, "uncovered", []) or [])
        p.evidence = [f"WebMCP readiness {score:.0f}/100"] + [f"form without a tool: {s}" for s in
                                                             uncovered[:EVIDENCE_LIMIT]]
    points.append(p)
    return points


def score(points: list[ReadinessPoint], tasks: Optional[list[TaskOutcome]] = None) -> ReadinessReport:
    measured = [p for p in points if p.status == "measured"]
    total_max = sum(p.max for p in points)
    m_max = sum(p.max for p in measured)
    static = 100 * sum(p.earned for p in measured) / m_max if m_max else None
    report = ReadinessReport(points=points, static_score=static,
                             static_coverage=m_max / total_max if total_max else 0.0,
                             dynamic_score=None, tasks=list(tasks or []))
    if tasks:
        report.dynamic_score = 100 * sum(t.succeeded for t in tasks) / len(tasks)
        unconfirmed = [t for t in tasks if not t.succeeded and not t.confirmed_failure]
        if unconfirmed:
            report.notes.append(f"{len(unconfirmed)} failed task(s) are not confirmed site defects "
                                "(needs review; could be the agent)")
    else:
        report.notes.append("dynamic readiness not measured: no agent tasks were run")
    if static is not None and report.dynamic_score is not None:
        report.overall = (static + report.dynamic_score) / 2
    else:
        report.overall = static if static is not None else report.dynamic_score
    if report.static_coverage < 1.0:
        missing = [p.id for p in points if p.status != "measured"]
        report.notes.append(f"static score based on {report.static_coverage:.0%} of points; "
                            f"not measured: {', '.join(missing)}")
    return report


def render_markdown(report: ReadinessReport, *, target: str = "") -> str:
    def f(x):
        return "—" if x is None else f"{x:.0f}"

    lines = [f"# Agent readiness{': ' + target if target else ''}", "",
             f"**Overall {f(report.overall)}/100** · static {f(report.static_score)} "
             f"(on {report.static_coverage:.0%} of points) · dynamic {f(report.dynamic_score)}", "",
             "| point | earned | max | evidence |", "|---|--:|--:|---|"]
    for p in report.points:
        earned = "not measured" if p.status != "measured" else f"{p.earned:.1f}"
        lines.append(f"| {p.label} | {earned} | {p.max:.0f} | {'; '.join(p.evidence)} |")
    if report.tasks:
        lines += ["", "| task | result |", "|---|---|"]
        for t in report.tasks:
            res = "completed" if t.succeeded else ("failed — confirmed site defect" if t.confirmed_failure
                                                  else "failed — needs review")
            lines.append(f"| {t.task} | {res} |")
    if report.notes:
        lines += [""] + [f"- {n}" for n in report.notes]
    return "\n".join(lines) + "\n"


# --- end to end: one URL -> a readiness report ------------------------------------

async def readiness_for(url: str, *, timeout: float = 120.0, worker_cmd: Optional[list[str]] = None,
                        stability: bool = False, tasks: Optional[list[TaskOutcome]] = None) -> ReadinessReport:
    """
    Render + scan the page (one `scan_url`), read its accessibility tree and
    DOM from the render artifacts, check WebMCP readiness on that DOM, and
    score. With `stability`, the page is scanned a second time to compare its
    controls (doubles the cost — off by default).
    """
    from pathlib import Path

    from verity.agents.virtual_sr import load_ax_tree
    from verity.observability import ScanTrace
    from verity.orchestrator.main import scan_url

    trace = ScanTrace()
    report = await scan_url(url, node_worker_command=worker_cmd, timeout=timeout, trace=trace)
    ax_path = trace.artifacts.get("ax_tree_path")
    if not ax_path:
        raise RuntimeError("the worker did not report an ax-tree.json for this render")
    tree = load_ax_tree(Path(ax_path))

    second = None
    if stability:
        t2 = ScanTrace()
        await scan_url(url, node_worker_command=worker_cmd, timeout=timeout, trace=t2)
        if t2.artifacts.get("ax_tree_path"):
            second = load_ax_tree(Path(t2.artifacts["ax_tree_path"]))

    webmcp = None
    dom_path = trace.artifacts.get("dom_path")
    if dom_path and Path(dom_path).exists():
        from verity.webmcp import check_readiness, extract_page_from_html

        webmcp = check_readiness(extract_page_from_html(Path(dom_path).read_text(encoding="utf-8",
                                                                                 errors="replace"), url))
    points = static_points(tree, findings=report.findings, second_tree=second, webmcp_report=webmcp)
    return score(points, tasks)
