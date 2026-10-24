"""
B11.2′ (Track B, Week 11) — the schema linter, run in CI.

The gate test is the first one: every closed vocabulary Verity ships in an
agent or checker output is classified, and every judgment carries an escape.
The rest pin the linter's own rules on small hand-built models, written (per
the plan's artifact) before any new schema they will govern.
"""

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel

from verity.schema_lint import Judgment, lint_json_schema, lint_models, lint_shipped


def test_every_shipped_output_schema_passes_the_linter():
    problems = lint_shipped()
    assert problems == [], "\n".join(map(str, problems))


def test_the_vision_judgment_schemas_handed_to_a_model_carry_escapes():
    from verity.agents.vision import AltTextJudgment, ContrastRegionLocalisation, FocusVisibleJudgment

    for model in (AltTextJudgment, FocusVisibleJudgment, ContrastRegionLocalisation):
        assert lint_json_schema(model.model_json_schema(), name=model.__name__) == []


# --- the rules ------------------------------------------------------------------------

class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class Judged(BaseModel):
    meaningful: Literal["yes", "no"]
    verdict: Verdict
    sure: bool
    measured: Optional[bool] = None
    label: Literal["a", "b"]


def test_a_judgment_with_no_escape_is_a_violation():
    v = lint_models([Judged], {"Judged.meaningful": Judgment(), "Judged.verdict": Judgment(),
                               "Judged.sure": Judgment(), "Judged.measured": Judgment()},
                    {"Judged.label": "a display label"})
    assert sorted(x.field for x in v) == ["meaningful", "sure", "verdict"]


def test_a_nullable_bool_is_its_own_escape():
    v = lint_models([Judged], {"Judged.measured": Judgment()},
                    {"Judged.meaningful": "x", "Judged.verdict": "x", "Judged.sure": "x", "Judged.label": "x"})
    assert v == []


def test_an_unclassified_closed_vocabulary_fails_ci():
    v = lint_models([Judged], {}, {})
    assert {x.field for x in v} == {"meaningful", "verdict", "sure", "measured", "label"}
    assert all("unclassified" in x.problem for x in v)


def test_an_exemption_needs_a_reason():
    v = lint_models([Judged], {"Judged.meaningful": Judgment(escape=frozenset({"yes"}))},
                    {"Judged.verdict": " ", "Judged.sure": "r", "Judged.measured": "r", "Judged.label": "r"})
    assert [x.field for x in v] == ["verdict"]


def test_a_stale_registry_entry_is_reported():
    v = lint_models([Judged], {"Judged.gone": Judgment()},
                    {"Judged.meaningful": "r", "Judged.verdict": "r", "Judged.sure": "r", "Judged.measured": "r",
                     "Judged.label": "r"})
    assert [x.field for x in v] == ["gone"]


class Outer(BaseModel):
    inner: list[Judged]


def test_nested_models_are_linted():
    assert {x.model for x in lint_models([Outer], {}, {})} == {"Judged"}


def test_bool_judgment_may_name_the_field_that_says_it_was_undecided():
    class Trav(BaseModel):
        trap_detected: bool
        complete: bool

    assert lint_models([Trav], {"Trav.trap_detected": Judgment(escape_via="complete")},
                       {"Trav.complete": "the flag"}) == []
    assert lint_models([Trav], {"Trav.trap_detected": Judgment(escape_via="nope")},
                       {"Trav.complete": "the flag"})


# --- JSON Schema (what a model is constrained by) --------------------------------------

def test_json_schema_enums_and_booleans_need_escapes():
    schema = {
        "properties": {
            "meaningful": {"enum": ["yes", "no", "unknown"]},
            "verdict": {"enum": ["pass", "fail"]},
            "sure": {"type": "boolean"},
            "maybe": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "box": {"anyOf": [{"$ref": "#/$defs/Box"}, {"type": "null"}]},
        },
        "$defs": {"Box": {"properties": {"kind": {"enum": ["a", "b"]}}}},
    }
    assert sorted(v.field for v in lint_json_schema(schema)) == ["box.kind", "sure", "verdict"]


def test_an_agent_action_set_escapes_with_its_own_vocabulary():
    schema = {"properties": {"actions": {"type": "array", "items": {"$ref": "#/$defs/Act"}}},
              "$defs": {"Act": {"properties": {"type": {"enum": ["click", "fill", "report_infeasible"]}}}}}
    assert lint_json_schema(schema)  # report_infeasible is not a generic escape…
    assert lint_json_schema(schema, escapes={"report_infeasible"}) == []  # …but it is this vocabulary's
