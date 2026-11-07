"""
B16.1 / B16.2 — the ACR (VPAT 2.5, WCAG 2.2 edition) generator (Track B,
Week 16; kept from the original B16.1–B16.3 and A16.2–A16.3).

An Accessibility Conformance Report is what a compliance officer reads, so the
rule for every row is the one the gate states: *presentable without
embarrassment or manual correction* — which means it must never claim more than
the evidence supports.

Every criterion gets a row (all 86 in force, plus 4.1.1 for completeness),
including the ones nobody can test automatically. Values follow VPAT 2.5:

| Evidence | Value |
|---|---|
| a human evaluation recorded for the criterion (`--manual`) | that value, as given |
| an authoritative failure on ≥ 50% of scanned pages | **Does Not Support** |
| an authoritative failure on fewer pages | **Partially Supports** |
| only AI-assisted / needs-review findings | **Not Evaluated** — labelled *AI-assisted finding — requires human verification* |
| automated checks ran and found nothing | **Not Evaluated** — automated checks cannot establish conformance |
| no automated check exists | **Not Evaluated** — requires human evaluation |

Two things this generator will never do:

- **Never "Supports" from automation.** A scan that found nothing is not proof
  of conformance (ADR-0004: a pass needs complete coverage). "Supports" and
  "Not Applicable" come only from a recorded human evaluation.
- **Never hide an unfinished report.** VPAT 2.5 does not allow "Not Evaluated"
  for Level A/AA; any such row marks the ACR `complete: False`, and the header
  says how many rows a human must still evaluate before it is published.

Remarks are written for a non-engineer: what was found, where (pages,
elements, finding ids for the engineers), and what to do about it.

    verity acr scan1.json scan2.json --product "Acme Store" --manual manual.yaml --out acr.md --html acr.html
"""

from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

from verity.models.schemas import AuditReport
from verity.standards import WCAG22, Criterion, how_tested, method

VALUES = ("Supports", "Partially Supports", "Does Not Support", "Not Applicable", "Not Evaluated")
AI_LABEL = "AI-assisted finding — requires human verification"
DOES_NOT_SUPPORT_SHARE = 0.5

REMEDIATION = {
    "1.1.1": "give every meaningful image a text alternative, and mark decorative images alt=\"\"",
    "1.3.1": "expose structure in markup: real headings, lists, table headers and form labels",
    "1.4.3": "raise text contrast to at least 4.5:1 (3:1 for large text)",
    "2.1.1": "make every control usable with the keyboard alone (native buttons and links, or key handlers)",
    "2.1.2": "make sure keyboard focus can always move out of every component",
    "2.4.3": "keep the keyboard focus order logical; avoid positive tabindex values",
    "2.4.7": "show a visible focus indicator on every focusable element",
    "4.1.2": "give every control an accessible name and the correct role and state",
}


@dataclass
class ManualResult:
    value: str
    remarks: str = ""
    evaluator: str = ""
    date: str = ""


@dataclass
class AcrRow:
    sc: str
    name: str
    level: str
    value: str
    remarks: str
    evidence: list[str] = field(default_factory=list)
    ai_assisted: bool = False
    needs_human: bool = False
    source: str = "automated"          # automated | manual | none


@dataclass
class Acr:
    product: str
    report_date: str
    pages: list[str]
    rows: list[AcrRow]
    levels: tuple[str, ...]

    @property
    def unevaluated(self) -> list[AcrRow]:
        return [r for r in self.rows if r.value == "Not Evaluated" and r.level in ("A", "AA")]

    @property
    def complete(self) -> bool:
        return not self.unevaluated


def load_manual(path: Optional[Path]) -> dict[str, ManualResult]:
    """Human evaluations: `{sc: {value, remarks, evaluator, date}}` in YAML. Values are validated."""
    if not path:
        return {}
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    out: dict[str, ManualResult] = {}
    for sc, spec in data.items():
        spec = spec if isinstance(spec, dict) else {"value": spec}
        if spec.get("value") not in VALUES:
            raise ValueError(f"{sc}: {spec.get('value')!r} is not a VPAT value ({', '.join(VALUES)})")
        out[str(sc)] = ManualResult(**{k: str(v) for k, v in spec.items() if k in
                                       ("value", "remarks", "evaluator", "date")})
    return out


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _row(c: Criterion, reports: list[AuditReport], manual: dict[str, ManualResult]) -> AcrRow:
    if c.obsolete:
        return AcrRow(c.id, c.name, c.level, "Not Applicable",
                      "Removed from WCAG 2.2 (obsolete); listed for completeness only.", source="none")
    if c.id in manual:
        m = manual[c.id]
        who = f" Evaluated by {m.evaluator}{', ' + m.date if m.date else ''}." if m.evaluator else ""
        return AcrRow(c.id, c.name, c.level, m.value, (m.remarks or "Human evaluation.") + who, source="manual")

    fails, others, pages_failing = [], [], set()
    for r in reports:
        for f in r.findings:
            if f.sc.id != c.id or f.waived:
                continue
            prov = getattr(f.provenance, "value", f.provenance)
            if prov == "authoritative" and f.outcome == "fail":
                fails.append((r.target, f))
                pages_failing.add(r.target)
            elif f.outcome in ("fail", "cantTell"):
                others.append((r.target, f))

    evidence = [f"{f.id} — {f.evidence.dom_selector or 'page'} on {page}" for page, f in (fails or others)[:8]]
    fix = REMEDIATION.get(c.id)
    if fails:
        share = len(pages_failing) / len(reports) if reports else 1.0
        value = "Does Not Support" if share >= DOES_NOT_SUPPORT_SHARE else "Partially Supports"
        remarks = (f"Automated testing found {_plural(len(fails), 'failure')} on "
                   f"{len(pages_failing)} of {_plural(len(reports), 'page')} tested "
                   f"({how_tested(c.id)}). " + (f"To fix: {fix}." if fix else ""))
        if others:
            remarks += f" A further {_plural(len(others), 'item')} need human review."
        return AcrRow(c.id, c.name, c.level, value, remarks.strip(), evidence)
    if others:
        ai = any(getattr(f.provenance, "value", f.provenance) == "ai assisted" for _, f in others)
        remarks = (f"{AI_LABEL + '. ' if ai else ''}Automated testing flagged {_plural(len(others), 'item')} it "
                   f"could not decide; a person must check them before this criterion can be rated."
                   + (f" If confirmed, to fix: {fix}." if fix else ""))
        return AcrRow(c.id, c.name, c.level, "Not Evaluated", remarks, evidence, ai_assisted=ai, needs_human=True)
    if method(c.id) == "manual":
        return AcrRow(c.id, c.name, c.level, "Not Evaluated",
                      "Not testable automatically; requires evaluation by a person.", needs_human=True, source="none")
    return AcrRow(c.id, c.name, c.level, "Not Evaluated",
                  f"Automated checks ({how_tested(c.id)}) found no failures on "
                  f"{_plural(len(reports), 'page')}. That is not proof of conformance; a person must confirm.",
                  needs_human=True)


def build_acr(reports: Iterable[AuditReport], *, product: str, manual: Optional[dict[str, ManualResult]] = None,
              levels: tuple[str, ...] = ("A", "AA"), report_date: Optional[str] = None) -> Acr:
    reports = list(reports)
    manual = manual or {}
    rows = [_row(c, reports, manual) for c in WCAG22 if c.level in levels or (c.obsolete and "A" in levels)]
    return Acr(product=product, report_date=report_date or date.today().isoformat(),
               pages=[r.target for r in reports], rows=rows, levels=levels)


def render_markdown(acr: Acr) -> str:
    lines = [f"# Accessibility Conformance Report — {acr.product}", "",
             f"**Based on VPAT® 2.5 (WCAG 2.2 edition)** · Report date {acr.report_date} · "
             f"Standard: WCAG 2.2 Level {' and '.join(acr.levels)}", ""]
    if not acr.complete:
        lines += [f"> **DRAFT — not ready to publish.** {len(acr.unevaluated)} Level A/AA criteria are "
                  "*Not Evaluated*, which VPAT 2.5 does not allow in a published report. A person must evaluate "
                  "them and record the results (`--manual`).", ""]
    lines += ["## Evaluation methods", "",
              f"Automated testing with Verity on {len(acr.pages)} page(s): "
              + ", ".join(acr.pages[:10]) + ("…" if len(acr.pages) > 10 else "") + ". "
              "Automated testing can show that a criterion fails; it cannot show that one is met. "
              f"Rows marked *{AI_LABEL}* came from model-assisted checks and are not conclusions.", "",
              "## Table 1: Success Criteria", "",
              "| Criteria | Conformance Level | Remarks and Explanations |", "|---|---|---|"]
    for r in acr.rows:
        remark = r.remarks.replace("|", "\\|")
        if r.evidence:
            remark += " <br>Evidence: " + "; ".join(e.replace("|", "\\|") for e in r.evidence)
        lines.append(f"| {r.sc} {r.name} (Level {r.level}) | {r.value} | {remark} |")
    counts = {v: sum(1 for r in acr.rows if r.value == v) for v in VALUES}
    lines += ["", "**Summary:** " + " · ".join(f"{v}: {n}" for v, n in counts.items()), ""]
    return "\n".join(lines)


def render_html(acr: Acr) -> str:
    e = _html.escape
    rows = "\n".join(
        f"<tr><th scope=\"row\">{e(r.sc)} {e(r.name)} <span>(Level {e(r.level)})</span></th>"
        f"<td>{e(r.value)}</td><td>{e(r.remarks)}"
        + (f"<details><summary>Evidence</summary><ul>{''.join(f'<li>{e(x)}</li>' for x in r.evidence)}</ul>"
           f"</details>" if r.evidence else "") + "</td></tr>"
        for r in acr.rows)
    banner = (f'<p role="alert"><strong>Draft — not ready to publish.</strong> {len(acr.unevaluated)} Level A/AA '
              "criteria still need human evaluation.</p>" if not acr.complete else "")
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>ACR — {e(acr.product)}</title>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem}"
            "table{border-collapse:collapse;width:100%}th,td{border:1px solid #888;padding:.4rem;vertical-align:top;"
            "text-align:left}th span{font-weight:normal}[role=alert]{border:2px solid #a00;padding:.6rem}</style>"
            f"</head><body><h1>Accessibility Conformance Report — {e(acr.product)}</h1>"
            f"<p>Based on VPAT® 2.5 (WCAG 2.2 edition) · {e(acr.report_date)} · {len(acr.pages)} page(s) tested</p>"
            f"{banner}<table><caption>Table 1: Success Criteria</caption><thead><tr><th scope=\"col\">Criteria</th>"
            f"<th scope=\"col\">Conformance Level</th><th scope=\"col\">Remarks and Explanations</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></body></html>\n")
