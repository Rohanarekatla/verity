"""
A17.1 — the bounded crawl frontier.

A readiness scan over a public site list must never wander: off the origin, past
a page cap, down an infinitely deep tree, or into logout/print/calendar traps.
The frontier enforces every configured limit *before* a URL is ever visited, and
records why a URL was skipped, so a bounded crawl is auditable, not just small.

URL normalisation is part of correctness, not cosmetics: `/a`, `/a/`, `/a#x` and
`/a?utm=1` are the same page for our purposes, and treating them as four would
blow the page budget on duplicates and re-scan identical content. The frontier
normalises before deduping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

# Query params that never change the page's content for accessibility purposes
# (tracking), stripped so they don't defeat dedup.
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|ref$|ref_src$|mc_)")


def normalize_url(url: str) -> str:
    """Canonical form for dedup: no fragment, no tracking params, no trailing
    slash on a path (except root), lowercased host."""
    url, _ = urldefrag(url)
    p = urlparse(url)
    host = p.netloc.lower()
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = "&".join(
        q for q in p.query.split("&")
        if q and not _TRACKING_PARAMS.match(q.split("=", 1)[0])
    )
    return urlunparse((p.scheme.lower(), host, path, "", query, ""))


@dataclass
class CrawlBounds:
    """The limits a crawl must respect. Every one is enforced in `allowed`."""

    max_pages: int = 25
    max_depth: int = 3
    same_origin: bool = True
    allowed_hosts: tuple[str, ...] = ()        # extra hosts beyond the seed's origin
    include: tuple[str, ...] = ()              # if set, a URL must match one (regex)
    exclude: tuple[str, ...] = (r"/logout", r"\.(pdf|zip|jpg|png|gif|svg|ico|css|js)$")

    def allowed(self, url: str, depth: int, origin: str) -> tuple[bool, str]:
        """Return (ok, reason). `reason` is empty when allowed."""
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            return False, f"non-http scheme {p.scheme!r}"
        if depth > self.max_depth:
            return False, f"depth {depth} > max_depth {self.max_depth}"
        if self.same_origin:
            hosts = {urlparse(origin).netloc.lower(), *(h.lower() for h in self.allowed_hosts)}
            if p.netloc.lower() not in hosts:
                return False, f"off-origin host {p.netloc!r}"
        if self.include and not any(re.search(pat, url) for pat in self.include):
            return False, "matches no include pattern"
        if any(re.search(pat, url, re.I) for pat in self.exclude):
            return False, "matches an exclude pattern"
        return True, ""


@dataclass
class CrawlFrontier:
    """A breadth-first frontier that enforces `bounds` and dedupes by normalised
    URL. `enqueued` counts URLs accepted (the page budget), not URLs seen."""

    origin: str
    bounds: CrawlBounds = field(default_factory=CrawlBounds)
    _queue: list[tuple[str, int]] = field(default_factory=list)
    _seen: set[str] = field(default_factory=set)
    skipped: dict[str, str] = field(default_factory=dict)  # url -> reason
    enqueued: int = 0

    def add(self, url: str, depth: int = 0, *, base: str = "") -> bool:
        """Offer a URL at `depth`. Returns True if it was enqueued."""
        resolved = urljoin(base or self.origin, url)
        norm = normalize_url(resolved)
        if norm in self._seen:
            return False
        if self.enqueued >= self.bounds.max_pages:
            self.skipped[norm] = f"page budget {self.bounds.max_pages} reached"
            self._seen.add(norm)
            return False
        ok, reason = self.bounds.allowed(norm, depth, self.origin)
        if not ok:
            self.skipped[norm] = reason
            self._seen.add(norm)
            return False
        self._seen.add(norm)
        self._queue.append((norm, depth))
        self.enqueued += 1
        return True

    def __bool__(self) -> bool:
        return bool(self._queue)

    def pop(self) -> tuple[str, int]:
        return self._queue.pop(0)
