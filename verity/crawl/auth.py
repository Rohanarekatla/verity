"""
A17.2 — authenticated crawling, with credentials that never touch the repo.

To scan pages behind a login, Verity uses a Playwright **storage state** (cookies
+ localStorage) captured once by the operator. The rule the plan sets is
absolute: credentials are *referenced by path*, never inlined into config and
never committed, and any secret must be scrubbed from traces and screenshots
before they are written.

So this module:

- loads a storage state **from a path** and refuses an inline credential blob
  (if you can paste it into config, it can be committed by accident);
- warns when that path sits inside the repo (where it could be staged);
- scrubs known secret values from any text (trace lines, logs) before it is
  persisted. Screenshot scrubbing is the caller's job at capture time; this
  provides the value set to redact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


class CredentialLeak(Exception):
    """Raised when credentials would be inlined or committed — refused loudly."""


@dataclass
class AuthConfig:
    """How to authenticate a crawl. Only a *path* to a storage state, plus the
    secret values to scrub from output — never the credentials themselves."""

    storage_state_path: Optional[str] = None
    scrub_values: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        # A storage_state given as a dict/JSON blob instead of a path is how a
        # credential ends up in a committed config file. Refuse it.
        if self.storage_state_path and self.storage_state_path.lstrip().startswith("{"):
            raise CredentialLeak(
                "storage_state must be a path, not an inline JSON blob — "
                "an inline credential can be committed by accident")


def load_storage_state(path: str, *, repo_root: Optional[Path] = None) -> dict:
    """
    Load a Playwright storage state from `path`. Warns (does not fail) if the
    file lives inside the repo, where it could be staged and committed.
    """
    import logging

    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"storage state not found at {path!r}")
    root = (repo_root or Path.cwd()).resolve()
    try:
        inside = p.resolve().is_relative_to(root)
    except (ValueError, OSError):
        inside = False
    if inside:
        logging.getLogger("verity.crawl.auth").warning(
            "storage state %s is inside the repo (%s); keep it out of version "
            "control (add it to .gitignore) so credentials are never committed", p, root)
    return json.loads(p.read_text(encoding="utf-8"))


def scrub_secrets(text: str, secrets, *, placeholder: str = "«redacted»") -> str:
    """
    Replace every secret value in `text` with `placeholder`. Longest-first so a
    secret that contains another is fully redacted. Empty/blank secrets are
    ignored (replacing "" would corrupt the whole string)."""
    if not text:
        return text
    out = text
    for secret in sorted((s for s in secrets if s and s.strip()), key=len, reverse=True):
        out = out.replace(secret, placeholder)
    return out
