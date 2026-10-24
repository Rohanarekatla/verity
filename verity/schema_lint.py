"""
B11.2′ — the schema linter: every closed vocabulary carries an escape.
(Track B, Week 11; kept from the original A11.1 + B11.2, ADR-0005.)

**The fabrication trap** (plan, Week 2 "Learning"): constrained decoding
produces well-formatted dishonesty when a required field has no supporting
evidence. Give a model — or a rushed checker — a field that must be `yes` or
`no`, and it will say one of them whether it saw anything or not. The cure is
structural: a judgment field's vocabulary must include a way to say "I could
not tell" (`unknown`, `cantTell`, `indeterminate`, …), so guessing is never
the only valid output.

The plan's artifact for this rule is to **write the rule before the schema it
governs**. So the linter does not wait to be told which fields are judgments:
every closed-vocabulary field (Literal, Enum, bool) in a registered agent or
checker output must be *classified* —

- a **judgment** — then its vocabulary must contain an escape, or (for a
  bool) it must be nullable or name the field that says it was undecided;
- or **not a judgment**, with the reason written down (a WCAG catalogue fact,
  a value copied from config, a policy output).

A new closed-vocabulary field nobody classified fails CI, so the decision is
made on purpose, once, in review — not discovered from a fabricated finding.

Two entry points:

- `lint_models()` — the Pydantic output models (run in CI by
  `verity/tests/test_schema_lint.py`);
- `lint_json_schema()` — a JSON Schema handed to a model for constrained
  decoding or tool use (agent action schemas, judgment schemas).
"""

from __future__ import annotations

import enum
import typing
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from pydantic import BaseModel

# Values that mean "I could not decide", across the vocabularies in use:
# WCAG-EM/ACT (`cantTell`), ADR-0004 (`indeterminate`), the contract runner
# (`notChecked`), provenance (`needs review`), and the generic ones.
ESCAPES = frozenset({
    "unknown", "insufficient_evidence", "cantTell", "notChecked", "indeterminate",
    "needs review", "needs_review",
})


@dataclass(frozen=True)
class Judgment:
    """A field that decides something. `escape` overrides ESCAPES for a domain value."""
    escape: Optional[frozenset] = None
    # For a bool judgment that cannot be nullable: the field that says the
    # decision could not be made (TraversalResult.trap_detected <- complete).
    escape_via: Optional[str] = None


@dataclass(frozen=True)
class Violation:
    model: str
    field: str
    problem: str

    def __str__(self) -> str:
        return f"{self.model}.{self.field}: {self.problem}"


# --- reading annotations --------------------------------------------------------------

@dataclass
class _Vocab:
    values: tuple
    is_bool: bool
    nullable: bool


def closed_vocabulary(annotation: Any) -> Optional[_Vocab]:
    """The closed set of values a field can hold, or None if it is open (str, int, …)."""
    values: list = []
    is_bool = False
    nullable = False
    found = False

    def visit(t: Any) -> None:
        nonlocal is_bool, nullable, found
        origin = typing.get_origin(t)
        if t is type(None):
            nullable = True
        elif origin is typing.Literal:
            found = True
            values.extend(typing.get_args(t))
        elif origin is typing.Annotated:
            visit(typing.get_args(t)[0])
        elif origin in (typing.Union, getattr(__import__("types"), "UnionType", None)):
            for a in typing.get_args(t):
                visit(a)
        elif t is bool:
            found = True
            is_bool = True
            values.extend([True, False])
        elif isinstance(t, type) and issubclass(t, enum.Enum):
            found = True
            values.extend(m.value for m in t)

    visit(annotation)
    return _Vocab(tuple(values), is_bool, nullable) if found else None


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    out: list[type[BaseModel]] = []

    def visit(t: Any) -> None:
        if isinstance(t, type) and issubclass(t, BaseModel):
            out.append(t)
            return
        for a in typing.get_args(t):
            visit(a)

    visit(annotation)
    return out


# --- the model linter -----------------------------------------------------------------

def lint_models(
    roots: Iterable[type[BaseModel]],
    judgments: dict[str, Judgment],
    not_judgments: dict[str, str],
) -> list[Violation]:
    """
    Lint every model reachable from `roots`. Keys are "Model.field".

    Violations: an unclassified closed-vocabulary field; a judgment with no
    escape; a non-judgment with no stated reason; and registry entries that
    name a field that no longer exists (a stale registry hides real drift).
    """
    violations: list[Violation] = []
    seen_models: set[type[BaseModel]] = set()
    seen_keys: set[str] = set()
    queue = list(roots)

    while queue:
        model = queue.pop()
        if model in seen_models:
            continue
        seen_models.add(model)
        for name, info in model.model_fields.items():
            queue.extend(_nested_models(info.annotation))
            vocab = closed_vocabulary(info.annotation)
            if vocab is None:
                continue
            key = f"{model.__name__}.{name}"
            seen_keys.add(key)
            if key in judgments:
                j = judgments[key]
                if vocab.is_bool and len(vocab.values) == 2:  # a plain (possibly Optional) bool
                    if vocab.nullable:
                        continue
                    if j.escape_via and j.escape_via in model.model_fields:
                        continue
                    violations.append(Violation(model.__name__, name,
                                                "bool judgment with no escape: make it Optional (None = could "
                                                "not tell) or name the field that says it was undecided"))
                    continue
                allowed = j.escape or ESCAPES
                if not set(map(str, vocab.values)) & set(map(str, allowed)):
                    violations.append(Violation(model.__name__, name,
                                                f"judgment vocabulary {sorted(map(str, vocab.values))} has no "
                                                f"escape (one of {sorted(map(str, allowed))})"))
            elif key in not_judgments:
                if not not_judgments[key].strip():
                    violations.append(Violation(model.__name__, name, "exempted with no reason"))
            else:
                violations.append(Violation(model.__name__, name,
                                            f"unclassified closed vocabulary {sorted(map(str, vocab.values))}: "
                                            "register it as a judgment (with an escape) or as not a judgment "
                                            "(with the reason)"))

    for key in sorted((set(judgments) | set(not_judgments)) - seen_keys):
        model, _, field = key.partition(".")
        violations.append(Violation(model, field, "registered in the linter but no such closed-vocabulary "
                                                  "field exists any more — remove or fix the entry"))
    return violations


# --- the JSON Schema linter (what a model is actually constrained by) ---------------

def lint_json_schema(schema: dict, *, name: str = "schema", exempt: Iterable[str] = (),
                     escapes: Iterable[str] = ESCAPES) -> list[Violation]:
    """
    Every enum and boolean property in a JSON Schema given to a model must
    carry an escape — unless exempted by property path ("actions[].type").

    A boolean with no null is the classic trap: there is no way to say
    "unknown". Use an enum with an escape instead.

    `escapes` widens the escape set for a domain vocabulary — an agent's
    action set escapes with BrowserGym's `report_infeasible`, not `unknown`.
    """
    exempt = set(exempt)
    escape_set = frozenset(escapes)
    violations: list[Violation] = []

    def resolve(node: dict) -> dict:
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            target: Any = schema
            for part in ref[2:].split("/"):
                target = target.get(part, {})
            return target
        return node

    def values_of(node: dict) -> tuple[list, bool, bool]:
        """(enum values, has boolean type, nullable) across anyOf/oneOf branches."""
        node = resolve(node)
        vals: list = list(node.get("enum", []))
        if "const" in node:
            vals.append(node["const"])
        types = node.get("type")
        types = types if isinstance(types, list) else [types]
        is_bool = "boolean" in types
        nullable = "null" in types or None in vals
        for branch in node.get("anyOf", []) + node.get("oneOf", []):
            v, b, n = values_of(branch)
            vals += v
            is_bool = is_bool or b
            nullable = nullable or n
        return vals, is_bool, nullable

    def walk(node: dict, path: str, seen: frozenset) -> None:
        node = resolve(node)
        for prop, sub in (node.get("properties") or {}).items():
            p = f"{path}.{prop}" if path else prop
            vals, is_bool, nullable = values_of(sub)
            if p not in exempt:
                if vals and not ({str(v) for v in vals if v is not None} & escape_set):
                    violations.append(Violation(name, p, f"enum {sorted(str(v) for v in vals)} has no escape"))
                elif is_bool and not nullable:
                    violations.append(Violation(name, p, "boolean with no way to say 'unknown' — use an enum "
                                                         "with an escape, or allow null"))
            target = resolve(sub)
            ref = sub.get("$ref")
            if ref in seen:
                continue
            nxt = seen | ({ref} if ref else set())
            walk(target, p, nxt)
            items = target.get("items")
            if isinstance(items, dict):
                walk(items, p + "[]", nxt)
            for branch in target.get("anyOf", []) + target.get("oneOf", []):
                walk(branch, p, nxt)

    walk(schema, "", frozenset())
    return violations


# --- what Verity ships, classified -----------------------------------------------------
#
# Registered roots: every model an agent or checker emits as a decision.
# Inventories and snapshots (WidgetInventory, ImageInventory, RegionSample)
# are measurements the worker reports, not decisions, and are not roots.

def shipped_registry() -> tuple[list[type[BaseModel]], dict[str, Judgment], dict[str, str]]:
    from eval.agentbench.analysis import EpisodeRecord
    from eval.agentbench.evaluators import EvaluationResult
    from verity.agents.image_triage import TriageResult
    from verity.agents.interaction import AssertionResult
    from verity.agents.vision import AltTextJudgment, ContrastRegionLocalisation, FocusVisibleJudgment
    from verity.models.schemas import AuditReport, TraversalResult

    roots: list[type[BaseModel]] = [
        AuditReport, AssertionResult, TraversalResult, AltTextJudgment, FocusVisibleJudgment,
        ContrastRegionLocalisation, TriageResult, EvaluationResult, EpisodeRecord,
    ]
    judgments = {
        "Finding.outcome": Judgment(),                        # cantTell
        "Finding.provenance": Judgment(),                     # needs review
        "AssertionResult.outcome": Judgment(),                # cantTell / notChecked
        "TraversalResult.trap_detected": Judgment(escape_via="complete"),
        "TraversalResult.returned_to_origin": Judgment(escape_via="complete"),
        "TabStop.focus_visible": Judgment(),                  # Optional: None = not measured
        "UnreachedRegion.reason": Judgment(),                 # unknown
        "AltTextJudgment.meaningful": Judgment(),             # unknown
        "FocusVisibleJudgment.focus_visible": Judgment(),     # unknown
        "ContrastRegionLocalisation.located": Judgment(),     # unknown
        # Triage only ever skips work; its fail-safe answer is "content" —
        # still an OCR candidate — which is the escape in this vocabulary.
        "TriageResult.category": Judgment(escape=frozenset({"content"})),
        "EvaluationResult.outcome": Judgment(),               # indeterminate
        "CheckResult.outcome": Judgment(),                    # indeterminate
        "EpisodeRecord.outcome": Judgment(),                  # indeterminate (excluded by rule)
    }
    not_judgments = {
        "Finding.severity": "policy output of assign_severity (B6.3), not an observation",
        "Finding.waived": "set from waivers.yaml, a recorded human decision",
        "SuccessCriterion.level": "WCAG catalogue fact (A/AA/AAA)",
        "SuccessCriterion.modality": "catalogue metadata: how the criterion is tested",
        "SuccessCriterion.obsolete": "WCAG catalogue fact (4.1.1)",
        "Confidence.escape_used": "telemetry: whether an escape was taken",
        "AuditReport.standard": "the requested conformance target — an input",
        "AssertionResult.severity": "copied from the contract YAML",
        "AssertionResult.section": "which contract section the assertion is in",
        "TraversalResult.complete": "the completeness flag itself — the escape for trap_detected and "
                                    "returned_to_origin",
        "TriageResult.ocr_candidate": "derived from category",
    }
    return roots, judgments, not_judgments


def lint_shipped() -> list[Violation]:
    roots, judgments, not_judgments = shipped_registry()
    return lint_models(roots, judgments, not_judgments)


if __name__ == "__main__":
    problems = lint_shipped()
    for v in problems:
        print(v)
    print(f"{len(problems)} schema-lint violation(s)")
    raise SystemExit(1 if problems else 0)
