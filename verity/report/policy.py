"""
verity/report/policy.py — configurable gating policy (B8.4).

Two separate questions that get conflated constantly:

- **`fail_on`** — what turns the build red?
- **`annotate_on`** — what appears in the report at all?

They are not the same, and the default reflects the whole product thesis:
annotate generously, fail narrowly. A finding that annotates costs a reader
five seconds. A finding that fails a build costs them an afternoon, and a
*wrong* one costs them the tool.

Default is `fail_on: authoritative` — only deterministic verdicts gate.
AI-assisted and needs-review findings are reported and never break CI, no
matter how severe they look.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from verity.models.schemas import Finding, Provenance

# Accepted `fail_on` / `annotate_on` values, loosest to strictest.
#
# "nothing" exists so a team can adopt Verity in report-only mode on day one,
# see the real scale of their backlog, and turn gating on deliberately. Week
# 7's waivers are the other half of that story; without either, the first
# install shows 300 failures and gets removed.
GATE_LEVELS: tuple[str, ...] = (
    "nothing",        # never fail / never annotate
    "authoritative",  # deterministic only  (DEFAULT for fail_on)
    "ai_assisted",    # + model-assisted    (DEFAULT for annotate_on)
    "everything",     # + needs-review
)

# Which provenances each level admits. Cumulative by design: choosing
# `ai_assisted` includes authoritative, because a policy where a stricter
# setting reports *fewer* things would be a trap.
_ADMITS: dict[str, frozenset[Provenance]] = {
    "nothing": frozenset(),
    "authoritative": frozenset({Provenance.AUTHORITATIVE}),
    "ai_assisted": frozenset({Provenance.AUTHORITATIVE, Provenance.AI_ASSISTED}),
    "everything": frozenset(
        {Provenance.AUTHORITATIVE, Provenance.AI_ASSISTED, Provenance.NEEDS_REVIEW}
    ),
}


class CiPolicy(BaseModel):
    """
    The `ci:` block of a Verity config.

    ```yaml
    ci:
      fail_on: authoritative     # default
      annotate_on: ai_assisted   # default
    ```
    """

    fail_on: str = Field(default="authoritative")
    annotate_on: str = Field(default="ai_assisted")

    model_config = {"extra": "forbid"}

    @field_validator("fail_on", "annotate_on")
    @classmethod
    def _known_level(cls, v: str) -> str:
        normalised = v.strip().lower().replace("-", "_").replace(" ", "_")
        if normalised not in GATE_LEVELS:
            raise ValueError(
                f"unknown gate level {v!r}; expected one of "
                f"{', '.join(GATE_LEVELS)}"
            )
        return normalised

    def _check_not_stricter_than_annotation(self) -> "CiPolicy":
        return self

    @property
    def fails_on(self) -> frozenset[Provenance]:
        return _ADMITS[self.fail_on]

    @property
    def annotates_on(self) -> frozenset[Provenance]:
        return _ADMITS[self.annotate_on]

    def gates(self, finding: Finding) -> bool:
        """
        Does this finding fail the build?

        Three conditions, all required:

        1. Its provenance is admitted by `fail_on`.
        2. Its outcome is `fail`. A `pass` is not a defect, and `cantTell`
           means we could not decide — neither may ever go red.
        3. It is not waived. A waiver is an accepted, justified failure
           (B7.2); the whole point is that it does not gate.
        """
        return (
            finding.provenance in self.fails_on
            and finding.outcome == "fail"
            and not finding.waived
        )

    def annotates(self, finding: Finding) -> bool:
        """
        Does this finding appear in the report?

        Waived findings **do** annotate. They are retained deliberately
        (B7.2): a reader should be able to see what was accepted and why,
        not discover a silent gap. They just do not gate.
        """
        return finding.provenance in self.annotates_on

    def gating_findings(self, findings: Iterable[Finding]) -> list[Finding]:
        return [f for f in findings if self.gates(f)]

    def annotated_findings(self, findings: Iterable[Finding]) -> list[Finding]:
        return [f for f in findings if self.annotates(f)]

    def describe(self) -> str:
        return f"fail_on={self.fail_on}, annotate_on={self.annotate_on}"


DEFAULT_POLICY = CiPolicy()


def load_policy(config_path: Optional[Path | str] = None) -> CiPolicy:
    """
    Read the `ci:` block from a config file, or return the default.

    A missing file is fine — the defaults are the documented behaviour and
    most projects will never write a config. A file that is present but has
    a bad `ci:` block raises: a typo'd `fail_on` silently falling back to
    the default would mean a team believes gating is off when it is on.
    """
    if config_path is None:
        return DEFAULT_POLICY

    path = Path(config_path)
    if not path.exists():
        return DEFAULT_POLICY

    with open(path, "r", encoding="utf-8") as f:
        data: Any = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level must be a mapping")

    ci = data.get("ci")
    if ci is None:
        return DEFAULT_POLICY
    if not isinstance(ci, dict):
        raise ValueError(f"{path}: 'ci' must be a mapping")

    return CiPolicy.model_validate(ci)
