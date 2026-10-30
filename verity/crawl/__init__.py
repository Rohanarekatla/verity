"""
Week 17 Track A — scale: crawl a site within bounds and a budget, cache what
doesn't change, and never commit credentials.

The Agent Readiness Report (B17.x) scans a large public site list, so Track A
supplies the machinery that makes that cheap and safe:

- **Bounded crawl** (A17.1) — a frontier that enforces every configured limit
  (pages, depth, same-origin, include/exclude), so a scan cannot wander.
- **Content-addressed cache** (A17.1) — findings keyed by (content hash, ruleset
  version, viewport), so an unchanged page state is skipped. The key includes
  everything that changes a finding; a missed invalidation would be a
  correctness bug wearing a performance costume.
- **Authenticated crawling** (A17.2) — a Playwright storage-state referenced by
  path, never inlined or committed, with secrets scrubbed from traces.
- **A budget gate** (A17.3) — a hard page/time cap so a 25-page audit fits a CI
  budget and stops cleanly rather than overrunning.
"""

from verity.crawl.auth import AuthConfig, load_storage_state, scrub_secrets
from verity.crawl.budget import BudgetExceeded, CrawlBudget
from verity.crawl.cache import CacheKey, FindingsCache
from verity.crawl.frontier import CrawlBounds, CrawlFrontier, normalize_url
from verity.crawl.site import PageResult, SiteReport, crawl_site

__all__ = [
    "AuthConfig", "load_storage_state", "scrub_secrets",
    "BudgetExceeded", "CrawlBudget",
    "CacheKey", "FindingsCache",
    "CrawlBounds", "CrawlFrontier", "normalize_url",
    "PageResult", "SiteReport", "crawl_site",
]
