"""
A17.1/A17.3 — the bounded, cached, budgeted site crawl.

Ties the frontier, cache and budget together into one loop that the Readiness
Report (B17.x) runs over a site list. The two expensive steps are split so the
cache can do its job across runs:

- `render_fn(url) -> RenderResult(content_hash, links)` — render the page, hash
  its state, extract links. Relatively cheap.
- `analyze_fn(url) -> findings` — the full accessibility analysis. Expensive, and
  skipped entirely when the cache already has findings for this content hash
  (+ ruleset version + viewport).

Both are injected, so the whole crawl is tested with in-memory fakes — no
browser, no network — including that an unchanged second run does zero analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from verity.crawl.budget import BudgetExceeded, CrawlBudget
from verity.crawl.cache import CacheKey, FindingsCache
from verity.crawl.frontier import CrawlBounds, CrawlFrontier


@dataclass
class RenderResult:
    content_hash: str
    links: list[str] = field(default_factory=list)


@dataclass
class PageResult:
    url: str
    depth: int
    content_hash: str
    findings: list
    from_cache: bool


@dataclass
class SiteReport:
    seeds: list[str]
    pages: list[PageResult] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)
    budget_stopped: bool = False
    cache_hits: int = 0

    @property
    def pages_scanned(self) -> int:
        return len(self.pages)

    @property
    def pages_from_cache(self) -> int:
        return sum(1 for p in self.pages if p.from_cache)

    @property
    def total_findings(self) -> int:
        return sum(len(p.findings) for p in self.pages)


def crawl_site(
    seeds: list[str],
    *,
    render_fn: Callable[[str], RenderResult],
    analyze_fn: Callable[[str], list],
    bounds: Optional[CrawlBounds] = None,
    budget: Optional[CrawlBudget] = None,
    cache: Optional[FindingsCache] = None,
    ruleset_version: str = "1.0.0",
    viewport: str = "default",
) -> SiteReport:
    """Crawl `seeds` within `bounds` and `budget`, caching findings by content."""
    if not seeds:
        return SiteReport(seeds=[])
    bounds = bounds or CrawlBounds()
    budget = budget or CrawlBudget(max_pages=bounds.max_pages)

    frontier = CrawlFrontier(origin=seeds[0], bounds=bounds)
    for s in seeds:
        frontier.add(s, 0)

    report = SiteReport(seeds=list(seeds))
    budget.start()
    while frontier:
        try:
            budget.ensure()
        except BudgetExceeded as exc:
            report.budget_stopped = True
            report.skipped["<budget>"] = exc.reason
            break

        url, depth = frontier.pop()
        render = render_fn(url)
        key = CacheKey(render.content_hash, ruleset_version, viewport)

        cached = cache.get(key) if cache else None
        if cached is not None:
            findings, from_cache = cached, True
        else:
            findings, from_cache = analyze_fn(url), False
            if cache:
                cache.put(key, findings)

        budget.record()
        report.pages.append(PageResult(url, depth, render.content_hash, findings, from_cache))
        for link in render.links:
            frontier.add(link, depth + 1, base=url)

    report.skipped.update(frontier.skipped)
    report.cache_hits = cache.hits if cache else 0
    return report
