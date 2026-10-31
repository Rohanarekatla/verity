"""
A17.1 — the content-addressed findings cache.

An unchanged page should not be re-scanned. The cache keys findings on the three
things that change them, and *only* those:

- **content hash** — the rendered page state (the same key `RenderArtifact` uses);
- **ruleset version** — a new ruleset can produce different findings on identical
  content, so a ruleset bump must invalidate every entry;
- **viewport** — a finding is attributed to a viewport (A17.3 of the original
  plan), so two viewports are two entries.

"Ruleset version" must mean *everything that can change a finding on identical
content*, not a hand-maintained string: `ruleset_fingerprint()` hashes the
Verity version, the axe-core version, every APG contract, the validator
(signature) version, the scan's check configuration, and the waiver file. The
reconciled invalidation set from the Week-17 artifact (both tracks' lists).

Miss any of these and the cache serves stale findings — a correctness bug
wearing a performance costume (the Week-17 artifact's warning). The key is
explicit here so the invalidation set is reviewable, not implicit in a hash of
"everything".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class CacheKey:
    content_hash: str
    ruleset_version: str
    viewport: str = "default"

    def digest(self) -> str:
        raw = f"{self.content_hash}|{self.ruleset_version}|{self.viewport}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def ruleset_fingerprint(repo: Optional[Path] = None) -> str:
    """A digest of everything besides page content that can change a finding."""
    repo = Path(repo) if repo else Path(__file__).resolve().parents[2]
    h = hashlib.sha256()

    def add(label: str, data: bytes) -> None:
        h.update(label.encode() + b"\0" + data + b"\0")

    try:
        from verity.agents.validator import VALIDATOR_VERSION
        from verity.orchestrator.main import MEASURE_FOCUS_VISIBLE
        add("validator", VALIDATOR_VERSION.encode())
        add("focus-visible", str(MEASURE_FOCUS_VISIBLE).encode())
    except Exception:  # never fail the cache over a missing import; the files below still key it
        add("validator", b"unknown")
    add("verity", (repo / "pyproject.toml").read_bytes() if (repo / "pyproject.toml").exists() else b"")
    axe = repo / "node-worker" / "node_modules" / "axe-core" / "package.json"
    lock = repo / "node-worker" / "package-lock.json"
    add("axe", axe.read_bytes() if axe.exists() else (lock.read_bytes() if lock.exists() else b""))
    for contract in sorted((repo / "data" / "apg-contracts").glob("*.yaml")):
        add(f"contract:{contract.name}", contract.read_bytes())
    waivers = repo / "waivers.yaml"
    add("waivers", waivers.read_bytes() if waivers.exists() else b"")
    return "rs-" + h.hexdigest()[:16]


class FindingsCache:
    """A filesystem cache of a page's findings, keyed by `CacheKey`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.hits = 0
        self.misses = 0

    def _path(self, key: CacheKey) -> Path:
        return self.root / f"{key.digest()}.json"

    def get(self, key: CacheKey) -> Optional[list[dict]]:
        path = self._path(key)
        if not path.exists():
            self.misses += 1
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            self.misses += 1
            return None
        self.hits += 1
        return data.get("findings", [])

    def put(self, key: CacheKey, findings: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "content_hash": key.content_hash,
            "ruleset_version": key.ruleset_version,
            "viewport": key.viewport,
            "findings": findings,
        }
        self._path(key).write_text(json.dumps(payload), encoding="utf-8")

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
