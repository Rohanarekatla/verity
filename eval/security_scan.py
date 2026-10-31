"""
S20.1 — the final security pass: no credentials in the repository, the run
artifacts, the traces, or anything that would be published.

    uv run python -m eval.security_scan                    # the repo (tracked + untracked, minus ignored dirs)
    uv run python -m eval.security_scan runs/ .verity/     # run outputs before publishing them

Exit 1 if anything is found, with the file, line and kind — never the secret
itself (the report must not become the leak).

Covers: Anthropic, OpenAI, GitHub, AWS, Google, Slack and generic bearer/API
keys, private-key blocks, and `Authorization:` headers in traces. Screenshots
cannot be read for text here, so image files under run directories are listed
for a human to check — reported, not silently passed.

Dependency audit (also S20.1), run alongside:

    cd node-worker && npm audit --omit=dev
    uvx pip-audit -r <(uv export --no-hashes)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

PATTERNS: dict[str, re.Pattern] = {
    "anthropic-key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai-key": re.compile(r"sk-(?!ant-)(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}"),
    "github-token": re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "google-api-key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "slack-token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "bearer-header": re.compile(r"(?i)authorization['\"]?\s*[:=]\s*['\"]?bearer\s+[A-Za-z0-9._~+/=-]{20,}"),
    "api-key-assignment": re.compile(r"(?i)\b(?:api[_-]?key|secret|token)\b['\"]?\s*[:=]\s*['\"][A-Za-z0-9_\-]{24,}['\"]"),
}
# Placeholders used in docs and tests are not secrets.
ALLOW = re.compile(r"(?i)sk-test|example|placeholder|xxxx|<[a-z_]+>|dummy|fake|REDACTED")
SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", ".pytest_cache", "vendor", "work"}
TEXT_SUFFIXES = {".py", ".ts", ".js", ".mjs", ".json", ".jsonl", ".md", ".yaml", ".yml", ".toml", ".txt", ".html",
                 ".htm", ".cfg", ".ini", ".env", ".sh", ".ps1", ".csv", ".sarif", ".xml", ".jsonld", ""}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class Hit:
    path: str
    line: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}"


def scan_text(text: str, path: str) -> list[Hit]:
    hits = []
    for n, line in enumerate(text.splitlines(), 1):
        for kind, pat in PATTERNS.items():
            for m in pat.finditer(line):
                if not ALLOW.search(m.group(0)):
                    hits.append(Hit(path, n, kind))
    return hits


def iter_files(roots: Iterable[Path]):
    for root in roots:
        root = Path(root)
        if root.is_file():
            yield root
            continue
        for p in root.rglob("*"):
            if p.is_file() and not (set(p.parts) & SKIP_DIRS):
                yield p


def scan(roots: Iterable[Path]) -> tuple[list[Hit], list[str]]:
    hits, images = [], []
    for p in iter_files(roots):
        if p.suffix.lower() in IMAGE_SUFFIXES:
            if "runs" in p.parts or ".verity" in p.parts:
                images.append(str(p))
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES or p.stat().st_size > 5_000_000:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        hits += scan_text(text, str(p))
    return hits, images


def main(argv: Optional[list[str]] = None) -> int:
    roots = [Path(a) for a in (argv if argv is not None else sys.argv[1:])] or [Path(".")]
    hits, images = scan(roots)
    for h in hits:
        print(f"SECRET? {h}")
    if images:
        print(f"{len(images)} screenshot(s) in run outputs need a human check before publishing, e.g. {images[0]}")
    print(f"{len(hits)} possible secret(s).")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
