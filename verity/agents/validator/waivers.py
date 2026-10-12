"""
verity/agents/validator/waivers.py — waiver schema and expiry (B7.1, B7.3).

Without waivers, the first team to install Verity sees several hundred
pre-existing failures and uninstalls it. That is the entire reason this file
exists, and it shapes every decision in it.

But a waiver is a decision to **stop looking at a real accessibility
defect**. Someone will rely on the thing we agreed not to fix. So the schema
is deliberately unforgiving: every field is required, and a waiver that has
passed its expiry date does not quietly keep working.

Two rules worth stating up front, because both are easy to get backwards:

1. **A malformed waiver is an error, not an ignored line.** Silently skipping
   a waiver whose `expires` was mistyped means the team believes a finding is
   suppressed when it is not — or, worse, the reverse.
2. **An expired waiver stops suppressing *and* fails CI.** Not one or the
   other. If it only stopped suppressing, the underlying finding would
   reappear with no explanation of why. If it only failed CI, the finding
   would stay hidden while the build broke for a reason nobody could see.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

# Where the waiver file lives. Resolved from this file, never the cwd — a
# waiver that silently stops applying because the CLI was run from another
# directory is an accepted failure quietly turning back into a build break.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WAIVERS_PATH = _REPO_ROOT / "waivers.yaml"

# How long a waiver may run before it has to be looked at again. Not enforced
# as a hard limit — a team may legitimately need longer — but recorded so the
# default template and the docs agree on what "reasonable" means.
SUGGESTED_MAX_TERM_DAYS = 365


class WaiverFileError(ValueError):
    """
    A waiver file that cannot be trusted.

    Raised rather than returning partial results: a half-loaded waiver file
    leaves the team with no idea which findings are suppressed.
    """


class Waiver(BaseModel):
    """
    One accepted, justified accessibility failure.

    **Every field is required** (B7.1). Each one answers a question that gets
    asked months later when nobody remembers the decision:

    - `signature` — which finding? Keyed to the dedup signature, so a waiver
      follows the defect rather than a line number.
    - `justification` — why was this acceptable? A waiver without a reason is
      indistinguishable from someone silencing a test.
    - `approved_by` — who decided? Accessibility waivers are somebody's
      accountability, not a config value.
    - `created` — when? Needed to tell a considered decision from one made in
      a hurry during a release.
    - `expires` — until when? The field that stops a waiver becoming
      permanent by default.

    `justification` has a minimum length because "n/a", "-" and "ok" are the
    three things people type when a field is required but not enforced, and
    none of them is a justification.
    """

    signature: str = Field(..., min_length=64, max_length=64)
    justification: str = Field(..., min_length=15)
    approved_by: str = Field(..., min_length=1, validation_alias="approved_by")
    created: date
    expires: date

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @field_validator("signature")
    @classmethod
    def _signature_is_hex(cls, v: str) -> str:
        if not all(c in "0123456789abcdef" for c in v.lower()):
            raise ValueError(
                "signature must be a 64-character hex sha256 digest"
            )
        return v.lower()

    @field_validator("justification")
    @classmethod
    def _justification_says_something(cls, v: str) -> str:
        placeholders = {
            "n/a", "na", "none", "tbd", "todo", "ok", "fixme",
            "no justification provided", "known issue", "wontfix",
        }
        if v.strip().lower().rstrip(".") in placeholders:
            raise ValueError(
                f"justification {v!r} is a placeholder, not a justification; "
                "say why this failure is acceptable"
            )
        return v

    @field_validator("expires")
    @classmethod
    def _expiry_is_after_creation(cls, v: date, info) -> date:
        created = (info.data or {}).get("created")
        if created is not None and v <= created:
            raise ValueError(
                f"expires ({v}) must be after created ({created}); a waiver "
                "that expires on or before the day it was written never "
                "suppressed anything"
            )
        return v

    def is_expired(self, today: Optional[date] = None) -> bool:
        """
        True once the expiry date has passed.

        The expiry day itself still counts as valid — `expires: 2026-12-31`
        means "good through the 31st", which is how everyone reads a date on
        a permission slip.
        """
        return (today or date.today()) > self.expires

    def days_remaining(self, today: Optional[date] = None) -> int:
        return (self.expires - (today or date.today())).days


def _coerce_approver(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accept `approver` as a spelling of `approved_by`.

    The execution plan names the field "approver"; the code and the shipped
    template use `approved_by`. Rather than make one of them wrong, both
    parse. `extra: forbid` would otherwise reject a file written from the
    plan, which would be a confusing first experience.
    """
    if "approver" in record and "approved_by" not in record:
        record = dict(record)
        record["approved_by"] = record.pop("approver")
    return record


def parse_waivers(data: Any, source: str = "<memory>") -> Dict[str, Waiver]:
    """
    Validate a loaded waiver document into `{signature: Waiver}`.

    Every error names the signature it belongs to. "Validation failed" with
    no location is useless in a file that may hold fifty entries.
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise WaiverFileError(f"{source}: top level must be a mapping")

    fingerprints = data.get("partialFingerprints") or {}
    if not isinstance(fingerprints, dict):
        raise WaiverFileError(
            f"{source}: 'partialFingerprints' must be a mapping of "
            "signature -> waiver record"
        )

    waivers: Dict[str, Waiver] = {}
    problems: list[str] = []

    for signature, record in fingerprints.items():
        if not isinstance(record, dict):
            problems.append(f"{signature[:12]}…: record must be a mapping")
            continue

        record = _coerce_approver({**record, "signature": signature})
        try:
            waivers[str(signature).lower()] = Waiver.model_validate(record)
        except ValidationError as exc:
            missing = sorted(
                str(e["loc"][0]) for e in exc.errors() if e["type"] == "missing"
            )
            if missing:
                problems.append(
                    f"{str(signature)[:12]}…: missing required field(s): "
                    f"{', '.join(missing)}"
                )
            else:
                detail = "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()
                )
                problems.append(f"{str(signature)[:12]}…: {detail}")

    if problems:
        raise WaiverFileError(
            f"{source}: {len(problems)} invalid waiver(s).\n  - "
            + "\n  - ".join(problems)
        )

    return waivers


def load_waivers(waivers_path: Optional[Path | str] = None) -> Dict[str, Waiver]:
    """
    Load and validate the waiver file. Missing file means no waivers.

    A missing file is fine — most projects have none. A *present but broken*
    file is not, and raises.
    """
    path = Path(waivers_path) if waivers_path is not None else DEFAULT_WAIVERS_PATH
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise WaiverFileError(f"{path}: not valid YAML: {exc}") from exc

    return parse_waivers(data, source=str(path))


# --- B7.3: expiry enforcement ---------------------------------------------

class ExpiredWaiver(BaseModel):
    """An expired waiver, with enough detail to act on it without digging."""

    signature: str
    approved_by: str
    justification: str
    expires: date
    days_overdue: int

    def describe(self) -> str:
        return (
            f"{self.signature[:12]}… expired {self.days_overdue} day(s) ago "
            f"on {self.expires} (approved by {self.approved_by}): "
            f"{self.justification}"
        )


def expired_waivers(
    waivers: Dict[str, Waiver], today: Optional[date] = None
) -> list[ExpiredWaiver]:
    """
    Every waiver past its expiry date, soonest-expired first.

    Returned rather than raised, so the caller decides the exit code. The
    CLI turns a non-empty list into a build failure that names each one
    (B7.3) — a waiver that lapses silently is a defect nobody is looking at
    any more and nobody has been told about.
    """
    at = today or date.today()
    out = [
        ExpiredWaiver(
            signature=signature,
            approved_by=waiver.approved_by,
            justification=waiver.justification,
            expires=waiver.expires,
            days_overdue=(at - waiver.expires).days,
        )
        for signature, waiver in waivers.items()
        if waiver.is_expired(at)
    ]
    return sorted(out, key=lambda e: e.expires)


def active_waivers(
    waivers: Dict[str, Waiver], today: Optional[date] = None
) -> Dict[str, Waiver]:
    """
    Only the waivers that still suppress.

    This is what `process_findings` applies. An expired waiver is absent
    here, so the finding it used to cover reappears and gates normally —
    which is the point of an expiry date.
    """
    at = today or date.today()
    return {s: w for s, w in waivers.items() if not w.is_expired(at)}


def expiring_soon(
    waivers: Dict[str, Waiver], within_days: int = 30, today: Optional[date] = None
) -> list[tuple[str, Waiver, int]]:
    """
    Waivers about to lapse, so a team can renew or fix before CI breaks.

    A hard expiry with no warning turns a deliberate policy into a surprise
    red build on an unrelated PR.
    """
    at = today or date.today()
    soon = [
        (s, w, w.days_remaining(at))
        for s, w in waivers.items()
        if not w.is_expired(at) and w.days_remaining(at) <= within_days
    ]
    return sorted(soon, key=lambda item: item[2])


def parse_date(value: str) -> date:
    """Parse an ISO date, for callers reading dates off the command line."""
    return datetime.strptime(value, "%Y-%m-%d").date()
