"""
verity/agents/validator/severity.py — severity assignment (B6.3).

Severity answers one question: **how badly is a real user blocked?**

It is not the same question as "how confident are we" (that is `confidence`)
or "who decided" (that is `provenance`). Keeping them separate matters,
because the three get conflated constantly and the result is a report where
everything is `critical` and nobody triages anything.

Until now severity came straight from axe's `impact` string with a
`moderate` fallback, and the keyboard agent hard-coded its own. Neither
accounted for whether the finding was even *decided*.
"""

from typing import Optional

from verity.models.schemas import Level, Provenance, Severity

# Criteria where failure blocks a user outright rather than degrading their
# experience. Keyboard access and non-text content are the classic examples:
# if you cannot reach a control at all, nothing else about the page matters.
#
# Deliberately short. A long list here would be a severity policy pretending
# to be a lookup table, and every entry needs a reason someone can argue with.
_BLOCKING_CRITERIA: frozenset[str] = frozenset({
    "1.1.1",   # Non-text Content — no alternative at all for a screen reader
    "2.1.1",   # Keyboard — the control cannot be operated
    "2.1.2",   # No Keyboard Trap — the user is stuck and must close the tab
    "2.4.7",   # Focus Visible — a keyboard user cannot see where they are
    "4.1.2",   # Name, Role, Value — assistive tech cannot describe the control
})

# axe's own impact ratings, mapped to ours. Used as a *hint*, never as the
# final word: axe rates the rule, not this instance of it.
_ENGINE_IMPACT: dict[str, Severity] = {
    "critical": Severity.CRITICAL,
    "serious": Severity.SERIOUS,
    "moderate": Severity.MODERATE,
    "minor": Severity.MINOR,
}

_ORDER: list[Severity] = [
    Severity.MINOR,
    Severity.MODERATE,
    Severity.SERIOUS,
    Severity.CRITICAL,
]


def _rank(severity: Severity) -> int:
    return _ORDER.index(severity)


def _cap(severity: Severity, ceiling: Severity) -> Severity:
    return severity if _rank(severity) <= _rank(ceiling) else ceiling


def assign_severity(
    sc_id: str,
    level: Level,
    outcome: str,
    provenance: Provenance,
    engine_impact: Optional[str] = None,
) -> Severity:
    """
    Decide how severely a finding blocks a user.

    The rules, in the order they apply:

    **1. An undecided finding is capped at MODERATE.** A `cantTell` says we
    could not determine whether anything is wrong. Labelling a maybe as
    `critical` is how a report becomes noise — the reader learns that
    `critical` does not mean critical, and then ignores the ones that are.
    The same cap applies to anything not `AUTHORITATIVE`: a model-assisted
    finding cannot claim the top of the scale.

    **2. A pass is always MINOR.** Severity describes a defect. A passing
    finding has none, and is recorded only so the conformance map can tell
    "checked and fine" from "never checked".

    **3. Blocking criteria are at least SERIOUS.** If the failure means the
    user cannot operate the control at all, the floor is raised regardless
    of what the engine said. Level A blocking failures are CRITICAL — level A
    is the floor of the standard, and a blocking failure of the floor is the
    worst thing this tool can find.

    **4. Otherwise trust the engine, then adjust for level.** axe's impact is
    a reasonable prior. Level AAA findings are capped at MODERATE, because
    AAA is explicitly not required for conformance and a AAA failure should
    never outrank a level A one.

    `engine_impact` is axe's `impact` string, or None when no engine offered
    an opinion — as with the keyboard agent, which derives severity entirely
    from the criterion.
    """
    if outcome == "pass":
        return Severity.MINOR

    # Start from the engine's opinion where there is one.
    base = _ENGINE_IMPACT.get((engine_impact or "").lower(), Severity.MODERATE)

    blocking = sc_id in _BLOCKING_CRITERIA

    if blocking:
        floor = Severity.CRITICAL if level is Level.A else Severity.SERIOUS
        if _rank(base) < _rank(floor):
            base = floor

    if level is Level.AAA:
        base = _cap(base, Severity.MODERATE)

    # Rules 1 and 2 are ceilings and apply last, so nothing above can raise a
    # finding past what its own certainty supports.
    if outcome == "cantTell" or provenance is not Provenance.AUTHORITATIVE:
        base = _cap(base, Severity.MODERATE)

    return base


def explain_severity(
    sc_id: str,
    level: Level,
    outcome: str,
    provenance: Provenance,
    engine_impact: Optional[str] = None,
) -> dict:
    """
    The severity plus why it came out that way.

    Worth recording on the finding: "why is this only moderate?" is the first
    question anyone asks of a triage list, and answering it from the report
    beats answering it from the source.
    """
    severity = assign_severity(sc_id, level, outcome, provenance, engine_impact)

    reasons: list[str] = []
    if outcome == "pass":
        reasons.append("passing findings carry no severity")
    else:
        if sc_id in _BLOCKING_CRITERIA:
            reasons.append(
                f"SC {sc_id} blocks operation outright; floor raised for level {level.value}"
            )
        if engine_impact:
            reasons.append(f"engine impact {engine_impact!r}")
        if level is Level.AAA:
            reasons.append("level AAA capped at moderate (not required for conformance)")
        if outcome == "cantTell":
            reasons.append("undecided findings capped at moderate")
        elif provenance is not Provenance.AUTHORITATIVE:
            reasons.append(
                f"provenance {provenance.value} is not authoritative; capped at moderate"
            )

    return {
        "severity": severity.value,
        "basis": reasons or ["engine impact, unadjusted"],
    }
