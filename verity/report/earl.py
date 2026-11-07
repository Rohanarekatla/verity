"""
B15.3 — EARL 1.0 (JSON-LD) report generator (Track B, Week 15; kept B15.1).

EARL is the W3C vocabulary ACT implementation reports are submitted in. One
`AuditReport` becomes one JSON-LD graph:

- one **Assertion per finding**, pointing at the element (CSS selector
  pointer) and the WCAG 2.2 criterion it was judged against;
- one **Assertion per criterion** with the page-level outcome from the
  conformance map;
- and — the honest part — an `earl:untested` assertion for every criterion in
  scope that no check attempted, so the report never reads as if silence
  meant "passed".

Outcome mapping (Verity → EARL), with `cantTell` kept as `cantTell` — an
undecided finding is never rounded to a pass or a fail:

    fail -> earl:failed   pass -> earl:passed   cantTell -> earl:cantTell
    (no check ran) -> earl:untested

Mode: `earl:automatic` for authoritative findings; `earl:semiAuto` for
AI-assisted and needs-review ones (a human must verify them). The shape was
hand-written first (`docs/earl-example.jsonld`, the Week 15 artifact).

    from verity.report.earl import write_earl
    write_earl(report, "report.earl.jsonld")
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from verity.models.schemas import AuditReport, Finding
from verity.standards import BY_ID, active, method

CONTEXT = {
    "earl": "http://www.w3.org/ns/earl#",
    "dct": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "ptr": "http://www.w3.org/2009/pointers#",
    "sch": "https://schema.org/",
    "WCAG22": "https://www.w3.org/TR/WCAG22/#",
    "ACT": "https://www.w3.org/WAI/standards-guidelines/act/rules/",
    "@vocab": "http://www.w3.org/ns/earl#",
}
ASSERTOR = {"@id": "https://github.com/Rohanarekatla/verity", "@type": ["earl:Assertor", "earl:Software"],
            "dct:title": "Verity"}
OUTCOME = {"fail": "earl:failed", "pass": "earl:passed", "cantTell": "earl:cantTell"}
LEVELS = {"WCAG2.2-AA": ("A", "AA"), "EN301549": ("A", "AA"), "508": ("A", "AA"), "INT": ("A", "AA")}


def wcag_anchor(sc_id: str) -> str:
    """The WCAG 2.2 Recommendation's fragment id for a criterion, e.g. 1.4.3 -> contrast-minimum."""
    c = BY_ID.get(sc_id)
    if c is None:
        return sc_id
    if c.obsolete:
        return "parsing"
    slug = re.sub(r"[^a-z0-9]+", "-", c.name.lower()).strip("-")
    return slug


def _test(sc_id: str) -> dict:
    c = BY_ID.get(sc_id)
    title = f"{sc_id} {c.name}" if c else sc_id
    return {"@id": f"WCAG22:{wcag_anchor(sc_id)}", "@type": "earl:TestRequirement", "dct:title": title}


def _mode(f: Finding) -> str:
    prov = getattr(f.provenance, "value", f.provenance)
    return "earl:automatic" if prov == "authoritative" else "earl:semiAuto"


def finding_assertion(f: Finding, subject: dict, date: str) -> dict:
    result = {"@type": "earl:TestResult", "outcome": OUTCOME.get(f.outcome, "earl:cantTell"),
              "description": f.message, "dct:date": date}
    if f.evidence.dom_selector:
        result["pointer"] = {"@type": "ptr:CSSSelectorPointer", "ptr:expression": f.evidence.dom_selector}
    prov = getattr(f.provenance, "value", f.provenance)
    if prov != "authoritative":
        result["description"] = f"[{prov} — requires human verification] {f.message}"
    a = {"@type": "Assertion", "assertedBy": ASSERTOR["@id"], "subject": subject, "test": _test(f.sc.id),
         "mode": _mode(f), "result": result, "dct:identifier": f.id}
    if f.sc.act_rule_ids:
        a["test"]["dct:isPartOf"] = [{"@id": f"ACT:{rid}"} for rid in f.sc.act_rule_ids]
    return a


def build_earl(report: AuditReport, *, date: Optional[str] = None, include_untested: bool = True) -> dict:
    date = date or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    subject = {"@type": ["earl:TestSubject", "sch:WebPage"], "dct:source": report.target}
    graph: list[dict] = [dict(ASSERTOR, **{"dct:hasVersion": report.verity_version})]
    for f in report.findings:
        if f.waived:
            continue
        graph.append(finding_assertion(f, subject, date))
    for sc_id, outcome in sorted(report.conformance.items()):
        graph.append({"@type": "Assertion", "assertedBy": ASSERTOR["@id"], "subject": subject,
                      "test": _test(sc_id), "mode": "earl:automatic",
                      "result": {"@type": "earl:TestResult", "outcome": OUTCOME.get(outcome, "earl:cantTell"),
                                 "description": f"page-level outcome for {sc_id} from {report.verity_version}",
                                 "dct:date": date}})
    if include_untested:
        levels = LEVELS.get(report.standard, ("A", "AA"))
        judged = set(report.conformance)
        for c in active():
            if c.level in levels and c.id not in judged:
                why = ("no automated check exists for this criterion; human evaluation required"
                       if method(c.id) == "manual" else
                       "automated checks ran and reported nothing for this criterion — that is not a pass; "
                       "human evaluation required")
                graph.append({"@type": "Assertion", "assertedBy": ASSERTOR["@id"], "subject": subject,
                              "test": _test(c.id), "mode": "earl:automatic",
                              "result": {"@type": "earl:TestResult", "outcome": "earl:untested",
                                         "description": why, "dct:date": date}})
    return {"@context": CONTEXT, "@graph": graph}


def write_earl(report: AuditReport, path, **kw) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(build_earl(report, **kw), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
