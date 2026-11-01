"""
B17.1′–B17.3′ — the Agent Readiness Report pipeline (Track B, Week 17).

The launch headline (plan v2, D4): how ready is the public web for AI agents —
measured, with the evidence published. Three stages, each resumable, each
writing JSON lines so a stopped run continues instead of starting over:

1. **Readiness scan** (B17.1′, deterministic, cheap) — every site in a list:
   a bounded crawl (Rohan's `crawl_site`: page/depth/time budget, same-origin,
   render_failed pages listed not fatal), and per page Verity's scan plus the
   agent-readiness points (B14.2′).

       uv run python -m eval.readiness_report scan sites.txt --out runs/readiness --pages 5

2. **Agent tasks on a sample** (B17.2′, budget-capped) — a seeded sample of the
   scanned sites; real tasks from a task file run through `verity agent-check`
   with deterministic confirmation (B14.1′). **Only confirmed failures are
   reported as site defects**; the rest are counted as "agent failed,
   unconfirmed".

       uv run python -m eval.readiness_report agents runs/readiness --tasks tasks.yaml \
           --sample 20 --model anthropic:claude-sonnet-5-5 --budget 50

3. **Report** (B17.3′) — aggregate tables and SVG figures (no plotting
   dependency) into `report.md`.

       uv run python -m eval.readiness_report report runs/readiness

Ethics and load: one site at a time, a page budget per site, and a fixed
user agent; the list is the operator's choice (e.g. a Tranco top-N CSV).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from statistics import fmean, median
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

SAMPLE_SEED = 20261214


# --- the site list ---------------------------------------------------------------------

def load_sites(path: Path) -> list[str]:
    """One URL (or bare domain) per line, or a Tranco-style CSV `rank,domain`. Deduplicated, order kept."""
    text = Path(path).read_text(encoding="utf-8")
    out: list[str] = []
    rows = csv.reader(text.splitlines())
    for row in rows:
        if not row or row[0].strip().startswith("#"):
            continue
        cell = row[-1].strip() if len(row) > 1 else row[0].strip()
        if not cell:
            continue
        url = cell if "://" in cell else f"https://{cell}/"
        if url not in out:
            out.append(url)
    return out


def sample_sites(sites: list[str], k: int, *, seed: int = SAMPLE_SEED) -> list[str]:
    """A seeded sample, so the agent-task subset is reproducible and not hand-picked."""
    pool = sorted(sites)
    return sorted(random.Random(seed).sample(pool, min(k, len(pool))))


# --- stage 1: the deterministic scan -------------------------------------------------------

@dataclass
class PageRecord:
    url: str
    content_hash: str = ""
    findings: int = 0
    authoritative_fails: int = 0
    fails_by_sc: dict[str, int] = field(default_factory=dict)
    static_score: Optional[float] = None
    static_coverage: float = 0.0
    points: dict[str, dict] = field(default_factory=dict)
    webmcp_tools: int = 0
    from_cache: bool = False


@dataclass
class SiteRecord:
    site: str
    pages: list[PageRecord] = field(default_factory=list)
    render_failed: dict[str, str] = field(default_factory=dict)
    budget_stopped: bool = False
    error: Optional[str] = None

    @property
    def score(self) -> Optional[float]:
        scores = [p.static_score for p in self.pages if p.static_score is not None]
        return fmean(scores) if scores else None


def page_record_from(url: str, report, readiness, *, content_hash: str, webmcp_tools: int = 0) -> PageRecord:
    fails = [f for f in report.findings
             if f.outcome == "fail" and getattr(f.provenance, "value", f.provenance) == "authoritative"
             and not f.waived]
    return PageRecord(
        url=url, content_hash=content_hash, findings=len(report.findings), authoritative_fails=len(fails),
        fails_by_sc=dict(Counter(f.sc.id for f in fails)), static_score=readiness.static_score,
        static_coverage=readiness.static_coverage,
        points={p.id: {"earned": p.earned, "max": p.max, "status": p.status} for p in readiness.points},
        webmcp_tools=webmcp_tools,
    )


async def _scan_page(url: str, *, timeout: float) -> tuple[PageRecord, list[str]]:
    """Scan one page; return its record and the same-document links found in its DOM."""
    from bs4 import BeautifulSoup

    from verity.agents.virtual_sr import load_ax_tree
    from verity.observability import ScanTrace
    from verity.orchestrator.main import scan_url
    from verity.readiness import score, static_points
    from verity.webmcp import check_readiness, extract_page_from_html

    trace = ScanTrace()
    report = await scan_url(url, timeout=timeout, trace=trace)
    tree = load_ax_tree(Path(trace.artifacts["ax_tree_path"]))
    html = Path(trace.artifacts["dom_path"]).read_text(encoding="utf-8", errors="replace") \
        if trace.artifacts.get("dom_path") else ""
    webmcp_page = extract_page_from_html(html, url)
    readiness = score(static_points(tree, findings=report.findings, webmcp_report=check_readiness(webmcp_page)))
    links = [urljoin(url, a.get("href")) for a in BeautifulSoup(html, "html.parser").find_all("a", href=True)]
    content_hash = trace.artifacts.get("content_hash", "")
    rec = page_record_from(url, report, readiness, content_hash=content_hash,
                           webmcp_tools=len(webmcp_page.tools))
    return rec, links


def scan_site(site: str, *, max_pages: int = 5, max_depth: int = 1, max_seconds: float = 300.0,
              timeout: float = 120.0, cache_dir: Optional[Path] = None,
              page_fn: Optional[Callable[[str], tuple[PageRecord, list[str]]]] = None) -> SiteRecord:
    """Bounded crawl of one site; per page the scan + readiness. `page_fn` is injectable for tests."""
    from verity.crawl import CrawlBounds, CrawlBudget, FindingsCache, crawl_site
    from verity.crawl.site import RenderResult

    page_fn = page_fn or (lambda u: asyncio.run(_scan_page(u, timeout=timeout)))
    stash: dict[str, PageRecord] = {}

    def render(url: str) -> RenderResult:
        rec, links = page_fn(url)
        stash[url] = rec
        return RenderResult(content_hash=rec.content_hash or url, links=links)

    def analyze(url: str) -> list:
        return [asdict(stash[url])]

    report = crawl_site(
        [site], render_fn=render, analyze_fn=analyze,
        bounds=CrawlBounds(max_pages=max_pages, max_depth=max_depth),
        budget=CrawlBudget(max_pages=max_pages, max_seconds=max_seconds),
        cache=FindingsCache(cache_dir) if cache_dir else None,
    )
    pages = []
    for p in report.pages:
        data = p.findings[0] if p.findings else None
        if data:
            rec = PageRecord(**data)
            rec.from_cache = p.from_cache
            pages.append(rec)
    return SiteRecord(site=site, pages=pages, render_failed=dict(report.render_failed),
                      budget_stopped=report.budget_stopped)


def _done(path: Path, key: str) -> set[str]:
    if not path.exists():
        return set()
    return {json.loads(l)[key] for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def run_scan(sites: list[str], out_dir: Path, *, scan_fn: Optional[Callable[[str], SiteRecord]] = None,
             **kw) -> Path:
    """Stage 1, resumable: sites already in `sites.jsonl` are skipped."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "sites.jsonl"
    done = _done(path, "site")
    scan_fn = scan_fn or (lambda s: scan_site(s, cache_dir=out_dir / "cache", **kw))
    for site in sites:
        if site in done:
            continue
        try:
            rec = scan_fn(site)
        except Exception as exc:  # one broken site never stops the report
            rec = SiteRecord(site=site, error=f"{exc.__class__.__name__}: {exc}"[:300])
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(rec)) + "\n")
    return path


def load_site_records(path: Path) -> list[SiteRecord]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        d["pages"] = [PageRecord(**p) for p in d.get("pages", [])]
        out.append(SiteRecord(**d))
    return out


# --- stage 2: agent tasks on a sample -------------------------------------------------------

@dataclass
class TaskRecord:
    site: str
    task: str
    verdict: str                  # passed | failed | infeasible | looped | error
    succeeded: bool
    confirmed: bool = False       # B14.1′ confirmed a site defect
    sc: Optional[str] = None
    selector: Optional[str] = None
    cost_usd: float = 0.0
    error: Optional[str] = None


def load_tasks(path: Path) -> dict[str, list[dict]]:
    """YAML: `{site_url: [{task: "...", success: {...optional evaluator spec...}}]}`; key `"*"` applies to all."""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return {k: [t if isinstance(t, dict) else {"task": t} for t in v] for k, v in data.items()}


def run_agent_tasks(sites: list[str], tasks: dict[str, list[dict]], out_dir: Path, *,
                    task_fn: Callable[[str, dict], TaskRecord]) -> Path:
    """Stage 2, resumable on (site, task)."""
    path = Path(out_dir) / "tasks.jsonl"
    done = set()
    if path.exists():
        for l in path.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                done.add((d["site"], d["task"]))
    for site in sites:
        for t in tasks.get(site, []) + tasks.get("*", []):
            if (site, t["task"]) in done:
                continue
            try:
                rec = task_fn(site, t)
            except Exception as exc:
                from eval.agentbench.providers import BudgetExceeded

                if isinstance(exc, BudgetExceeded):
                    return path      # budget is a gate: stop, keep what ran
                rec = TaskRecord(site=site, task=t["task"], verdict="error", succeeded=False,
                                 error=f"{exc.__class__.__name__}: {exc}"[:300])
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(rec)) + "\n")
    return path


def agent_check_task(site: str, task: dict, *, provider, headless: bool = True) -> TaskRecord:
    """One real agent-check run with deterministic confirmation (B14.1′)."""
    from eval.agentbench.agents.tree_agent import TreeAgent
    from eval.agentbench.evaluators import evaluate, observation_from_page
    from eval.agentbench.loop_guard import LoopGuard
    from eval.agentbench.web_env import WebEnv
    from verity.agent_check.check import agent_check
    from verity.agent_check.confirm import make_confirm_fn

    spec = task.get("success")
    success_fn = None
    if spec:
        def success_fn(env, _spec=spec):  # noqa: E306
            return evaluate(_spec, observation_from_page(env.page, _spec), task_id=site).outcome
    agent = TreeAgent(provider, loop_guard=LoopGuard())
    with WebEnv(site, goal=task["task"], headless=headless) as env:
        result = agent_check(site, task["task"], agent=agent, env=env, success_fn=success_fn,
                             confirm_fn=make_confirm_fn(env))
    f = result.findings[0] if result.findings else None
    confirmed = bool(f and getattr(f.provenance, "value", f.provenance) == "authoritative")
    return TaskRecord(site=site, task=task["task"], verdict=result.verdict, succeeded=result.succeeded,
                      confirmed=confirmed, sc=f.sc.id if f else None,
                      selector=f.evidence.dom_selector if f else None)


def load_task_records(path: Path) -> list[TaskRecord]:
    if not Path(path).exists():
        return []
    return [TaskRecord(**json.loads(l)) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


# --- stage 3: analysis + figures -------------------------------------------------------------

def analyze(sites: list[SiteRecord], tasks: Optional[list[TaskRecord]] = None) -> dict:
    scanned = [s for s in sites if s.pages]
    scores = [s.score for s in scanned if s.score is not None]
    pages = [p for s in scanned for p in s.pages]
    unnamed_sites = [s for s in scanned if any(
        p.points.get("named_controls", {}).get("status") == "measured"
        and p.points["named_controls"]["earned"] < p.points["named_controls"]["max"] for p in s.pages)]
    sc_sites = Counter(sc for s in scanned for sc in {sc for p in s.pages for sc in p.fails_by_sc})
    webmcp_sites = [s for s in scanned if any(p.webmcp_tools for p in s.pages)]
    out = {
        "sites_listed": len(sites), "sites_scanned": len(scanned),
        "sites_failed": [s.site for s in sites if not s.pages],
        "pages_scanned": len(pages), "pages_render_failed": sum(len(s.render_failed) for s in sites),
        "score_median": median(scores) if scores else None, "score_mean": fmean(scores) if scores else None,
        "scores": sorted(scores),
        "share_sites_with_unnamed_controls": len(unnamed_sites) / len(scanned) if scanned else None,
        "share_sites_declaring_webmcp": len(webmcp_sites) / len(scanned) if scanned else None,
        "top_failing_sc": sc_sites.most_common(10),
    }
    if tasks:
        # "inconclusive" = the agent never acted (unparseable output): like an
        # error, it says nothing about the site, so it is not a failed task.
        ran = [t for t in tasks if t.verdict not in ("error", "inconclusive")]
        failed = [t for t in ran if not t.succeeded]
        out["tasks"] = {
            "run": len(ran), "errors": len(tasks) - len(ran),
            "completed": sum(t.succeeded for t in ran),
            "completion_rate": (sum(t.succeeded for t in ran) / len(ran)) if ran else None,
            "failed_confirmed": sum(t.confirmed for t in failed),
            "failed_unconfirmed": sum(not t.confirmed for t in failed),
            "confirmed_by_sc": Counter(t.sc for t in failed if t.confirmed).most_common(),
        }
    return out


def svg_histogram(values: list[float], *, bins: int = 10, title: str = "", lo: float = 0, hi: float = 100) -> str:
    """A small, accessible SVG histogram (title + desc, no external dependency)."""
    counts = [0] * bins
    for v in values:
        i = min(bins - 1, max(0, int((v - lo) / (hi - lo) * bins)))
        counts[i] += 1
    w, h, pad = 520, 240, 30
    bw = (w - 2 * pad) / bins
    peak = max(counts) or 1
    bars = []
    for i, c in enumerate(counts):
        bh = (h - 2 * pad) * c / peak
        x, y = pad + i * bw, h - pad - bh
        a, b = lo + i * (hi - lo) / bins, lo + (i + 1) * (hi - lo) / bins
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw - 2:.1f}" height="{bh:.1f}" fill="#2b6cb0">'
                    f'<title>{a:.0f}–{b:.0f}: {c} site(s)</title></rect>')
        if i % 2 == 0:
            bars.append(f'<text x="{x:.1f}" y="{h - 10}" font-size="11">{a:.0f}</text>')
    desc = ", ".join(f"{lo + i * (hi - lo) / bins:.0f}–{lo + (i + 1) * (hi - lo) / bins:.0f}: {c}"
                     for i, c in enumerate(counts))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">'
            f'<title id="t">{title}</title><desc id="d">{desc}</desc>'
            f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#333"/>{"".join(bars)}</svg>\n')


def svg_bars(items: list[tuple[str, float]], *, title: str = "", unit: str = "") -> str:
    """Horizontal bars, labelled; accessible title/desc."""
    w, row, pad = 560, 24, 140
    h = row * len(items) + 20
    peak = max((v for _, v in items), default=1) or 1
    parts = []
    for i, (label, v) in enumerate(items):
        y = 10 + i * row
        bw = (w - pad - 60) * v / peak
        parts.append(f'<text x="0" y="{y + 15}" font-size="12">{label}</text>'
                     f'<rect x="{pad}" y="{y + 3}" width="{bw:.1f}" height="16" fill="#2f855a"/>'
                     f'<text x="{pad + bw + 4:.1f}" y="{y + 15}" font-size="12">{v:g}{unit}</text>')
    desc = "; ".join(f"{l}: {v:g}{unit}" for l, v in items)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">'
            f'<title id="t">{title}</title><desc id="d">{desc}</desc>{"".join(parts)}</svg>\n')


def render_report(stats: dict, *, figures_dir: Optional[Path] = None) -> str:
    def pct(x):
        return "—" if x is None else f"{100 * x:.0f}%"

    lines = ["# Agent Readiness Report", "",
             f"{stats['sites_scanned']} of {stats['sites_listed']} sites scanned ({stats['pages_scanned']} pages; "
             f"{stats['pages_render_failed']} pages failed to render and are excluded, not scored).", "",
             "## Static readiness (deterministic)", "",
             f"- Median readiness score: **{_f(stats['score_median'])}/100** (mean {_f(stats['score_mean'])})",
             f"- Sites with at least one control an agent cannot address (no accessible name): "
             f"**{pct(stats['share_sites_with_unnamed_controls'])}**",
             f"- Sites declaring WebMCP tools: **{pct(stats['share_sites_declaring_webmcp'])}**", "",
             "| Criterion | Sites with an authoritative failure |", "|---|--:|"]
    lines += [f"| {sc} | {n} |" for sc, n in stats["top_failing_sc"]] or ["| — | 0 |"]
    if stats["sites_failed"]:
        lines += ["", f"Sites that could not be scanned at all ({len(stats['sites_failed'])}): "
                  + ", ".join(stats["sites_failed"][:20])]
    if "tasks" in stats:
        t = stats["tasks"]
        lines += ["", "## Real agent tasks (sampled sites)", "",
                  f"- Tasks run: {t['run']} (errors excluded: {t['errors']})",
                  f"- Completed by the agent: **{pct(t['completion_rate'])}**",
                  f"- Failures **confirmed** as site defects by Verity: {t['failed_confirmed']}; "
                  f"unconfirmed (could be the agent): {t['failed_unconfirmed']}", "",
                  "Only confirmed failures are attributed to the site."]
    if figures_dir:
        lines += ["", "## Figures", "", "![Readiness score distribution](figures/scores.svg)",
                  "", "![Most common agent-blocking failures](figures/top_sc.svg)"]
    return "\n".join(lines) + "\n"


def _f(x):
    return "—" if x is None else f"{x:.0f}"


def write_report(out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    sites = load_site_records(out_dir / "sites.jsonl")
    tasks = load_task_records(out_dir / "tasks.jsonl")
    stats = analyze(sites, tasks or None)
    fig = out_dir / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    (fig / "scores.svg").write_text(svg_histogram(stats["scores"], title="Agent readiness score per site"),
                                    encoding="utf-8")
    (fig / "top_sc.svg").write_text(svg_bars([(sc, float(n)) for sc, n in stats["top_failing_sc"]],
                                             title="Sites with an authoritative failure, by criterion"),
                                    encoding="utf-8")
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
    path = out_dir / "report.md"
    path.write_text(render_report(stats, figures_dir=fig), encoding="utf-8")
    return path


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Agent Readiness Report")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("sites", type=Path)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--pages", type=int, default=5)
    s.add_argument("--depth", type=int, default=1)
    a = sub.add_parser("agents")
    a.add_argument("out", type=Path)
    a.add_argument("--tasks", type=Path, required=True)
    a.add_argument("--sample", type=int, default=20)
    a.add_argument("--model", required=True)
    a.add_argument("--budget", type=float, required=True, help="hard USD cap for the whole stage")
    r = sub.add_parser("report")
    r.add_argument("out", type=Path)
    args = p.parse_args(argv)

    if args.cmd == "scan":
        print(run_scan(load_sites(args.sites), args.out, max_pages=args.pages, max_depth=args.depth))
    elif args.cmd == "agents":
        from eval.agentbench.providers import CostLedger, make_provider

        scanned = [s.site for s in load_site_records(args.out / "sites.jsonl") if s.pages]
        provider = make_provider(args.model, ledger=CostLedger(cap_usd=args.budget,
                                                               path=args.out / "agent-ledger.jsonl"))
        sample = sample_sites(scanned, args.sample)
        print(run_agent_tasks(sample, load_tasks(args.tasks), args.out,
                              task_fn=lambda site, t: agent_check_task(site, t, provider=provider)))
    else:
        print(write_report(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
