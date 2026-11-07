"""
B14.3 — per-criterion precision / recall, reproducible with one command, and
the baseline freeze that makes a regression fail CI (Track B, Week 14; kept
from the original B14.1, B14.3, B14.4).

    cd node-worker && npm run build && cd ..
    uv run python -m eval.precision_recall                       # measure, print
    uv run python -m eval.precision_recall --freeze 0.1.0        # write eval/baselines/0.1.0.json
    uv run python -m eval.precision_recall --check 0.1.0         # exit 1 on any regression (CI)

The corpus is labelled by construction, so its ground truth is not anyone's
opinion:

- the **defect fixtures** in `data/fixtures/` — one known defect each, on a
  known element, under a known criterion (`FIXTURE_LABELS`);
- their **clean twins** (the APG pass fixtures and friends), which must produce
  no authoritative failure for the criteria they exercise (`EXHAUSTIVE`);
- every **injected ARIA misuse** (B9.4): a clean APG fixture with exactly one
  defect applied by `eval.inject.aria_misuse`, labelled with the criterion the
  broken contract assertion maps to (`MISUSE_LABELS`).

Only **authoritative failures** count as detections — they are what gates a
build. Needs-review findings on a labelled target are reported alongside as
`review`, never as a catch.

Competitor comparison (B14.2, "recall strictly exceeds axe-core alone at equal
or lower FP") is the BC-C2 benchmark, `eval/benchmark/benchmark.py`; this
harness is Verity's own regression net.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "data" / "fixtures"
BASELINES = REPO / "eval" / "baselines"


@dataclass(frozen=True)
class Label:
    page: str          # path under data/fixtures, or "misuse:<n>" for a generated variant
    sc: str
    target: str        # element id
    truth: str         # "fail" | "pass"


# One known defect per page, on a known element, under a known criterion.
FIXTURE_LABELS: tuple[Label, ...] = (
    Label("keyboard-trap.html", "2.1.2", "trap", "fail"),
    Label("keyboard-unreachable.html", "2.1.1", "stranded", "fail"),
    Label("keyboard-positive-tabindex.html", "2.4.3", "jumped", "fail"),
    Label("keyboard-focus-within.html", "2.4.7", "bare", "fail"),
    Label("keyboard-focus-within.html", "2.4.7", "wrapped", "pass"),
    Label("contrast-fail.html", "1.4.3", "low-contrast-text", "fail"),
    Label("contrast-pass.html", "1.4.3", "ok-contrast-text", "pass"),
    Label("apg/disclosure-fail.html", "2.1.1", "faq-1", "fail"),
    Label("apg/menu-button-fail.html", "2.4.3", "actions", "fail"),
    Label("apg/tablist-fail.html", "2.1.1", "tabs", "fail"),
    Label("apg/dialog-fail.html", "2.4.3", "open-address", "fail"),
    Label("apg/combobox-fail.html", "2.1.1", "fruit", "fail"),
)

# Clean pages: NO authoritative failure is allowed for these criteria anywhere
# on the page — every one there is a false positive.
KEYBOARD_AND_NAME = ("2.1.1", "2.1.2", "2.4.3", "2.4.7", "4.1.2")
EXHAUSTIVE: dict[str, tuple[str, ...]] = {
    "apg/disclosure-pass.html": KEYBOARD_AND_NAME,
    "apg/menu-button-pass.html": KEYBOARD_AND_NAME,
    "apg/tablist-pass.html": KEYBOARD_AND_NAME,
    "apg/dialog-pass.html": KEYBOARD_AND_NAME,
    "apg/combobox-pass.html": KEYBOARD_AND_NAME,
    "keyboard-tablist.html": KEYBOARD_AND_NAME,
    "keyboard-iframe.html": KEYBOARD_AND_NAME,
    "contrast-pass.html": ("1.4.3",),
}

# (pass fixture, injector, selector, criterion, target id) — the B9.4 cases.
MISUSE_LABELS: tuple[tuple[str, str, str, str, str], ...] = (
    ("apg/disclosure-pass.html", "click_only_widget", "#faq-1", "2.1.1", "faq-1"),
    ("apg/dialog-pass.html", "click_only_widget", "#open-address", "2.1.1", "open-address"),
    ("apg/menu-button-pass.html", "click_only_widget", "#actions", "2.1.1", "actions"),
    ("apg/menu-button-pass.html", "strip_accessible_name", "#actions", "4.1.2", "actions"),
    ("apg/disclosure-pass.html", "invalid_aria_state", "#faq-1", "4.1.2", "faq-1"),
    ("apg/combobox-pass.html", "invalid_aria_state", "#state", "4.1.2", "state"),
    ("apg/menu-button-pass.html", "dangling_idref", "#actions", "4.1.2", "actions"),
    ("apg/dialog-pass.html", "dangling_idref", "#open-address", "4.1.2", "open-address"),
    ("apg/combobox-pass.html", "dangling_idref", "#state", "4.1.2", "state"),
    ("apg/tablist-pass.html", "remove_from_tab_order", '[role="tab"]', "2.1.1", "tabs"),
)


def manifest_digest() -> str:
    """Identity of the corpus: labels + injector cases + the fixture bytes."""
    h = hashlib.sha256()
    h.update(json.dumps([asdict(x) for x in FIXTURE_LABELS], sort_keys=True).encode())
    h.update(json.dumps(EXHAUSTIVE, sort_keys=True).encode())
    h.update(json.dumps(MISUSE_LABELS).encode())
    pages = sorted({x.page for x in FIXTURE_LABELS} | set(EXHAUSTIVE) | {m[0] for m in MISUSE_LABELS})
    for p in pages:
        h.update(p.encode())
        h.update((FIXTURES / p).read_bytes())
    return h.hexdigest()


# --- matching findings to elements --------------------------------------------------

_ID = re.compile(r"#([A-Za-z_][\w-]*)")


def finding_targets(f: dict) -> set[str]:
    """Element ids a finding names: its selector plus the lists keyboard findings carry."""
    sels = [f.get("evidence", {}).get("dom_selector") or ""]
    cv = f.get("evidence", {}).get("computed_values") or {}
    for key in ("unreachable", "no_indicator"):
        sels += [s for s in cv.get(key) or [] if isinstance(s, str)]
    sels += [d.get("selector", "") for d in cv.get("positive_tabindex") or [] if isinstance(d, dict)]
    out: set[str] = set()
    for s in sels:
        out.update(_ID.findall(s or ""))
    return out


# --- scoring (pure) ------------------------------------------------------------------

def score(labels: Iterable[Label], findings_by_page: dict[str, list[dict]],
          exhaustive: Optional[dict[str, tuple[str, ...]]] = None) -> dict[str, dict]:
    """Per-SC tp / fp / fn / tn / review, precision, recall, F1."""
    exhaustive = exhaustive or {}
    stats: dict[str, dict] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0, "review": 0})
    labelled_hits: set[tuple] = set()
    for lab in labels:
        page_findings = findings_by_page.get(lab.page, [])
        auth = [f for f in page_findings if f["sc"]["id"] == lab.sc and f["outcome"] == "fail"
                and f["provenance"] == "authoritative" and lab.target in finding_targets(f)]
        review = [f for f in page_findings if f["sc"]["id"] == lab.sc and f["provenance"] != "authoritative"
                  and lab.target in finding_targets(f)]
        s = stats[lab.sc]
        for f in auth:
            labelled_hits.add((lab.page, f["id"]))
        if lab.truth == "fail":
            s["tp" if auth else "fn"] += 1
            if not auth and review:
                s["review"] += 1
        else:
            s["fp" if auth else "tn"] += 1
    for page, scs in exhaustive.items():
        for f in findings_by_page.get(page, []):
            if (f["sc"]["id"] in scs and f["outcome"] == "fail" and f["provenance"] == "authoritative"
                    and (page, f["id"]) not in labelled_hits):
                stats[f["sc"]["id"]]["fp"] += 1
        for sc in scs:
            stats[sc]  # every exhaustive criterion appears, even with zero counts
    for s in stats.values():
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        s["precision"] = tp / (tp + fp) if tp + fp else None
        s["recall"] = tp / (tp + fn) if tp + fn else None
        p, r = s["precision"], s["recall"]
        s["f1"] = (2 * p * r / (p + r)) if p and r else (0.0 if (p == 0 or r == 0) else None)
    return dict(sorted(stats.items()))


# --- baseline freeze / regression check ----------------------------------------------

def freeze(per_sc: dict, version: str, *, digest: str, path: Optional[Path] = None) -> Path:
    from verity.agents.validator import VALIDATOR_VERSION

    path = path or BASELINES / f"{version}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verity_version": version, "validator_version": VALIDATOR_VERSION,
                                "manifest_sha256": digest, "per_sc": per_sc}, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def compare_to_baseline(current: dict, frozen: dict, *, digest: str) -> list[str]:
    """
    Regressions against a frozen baseline (empty = no regression). Comparing on
    a different corpus is refused, not attempted: the numbers would not mean
    the same thing.
    """
    if frozen.get("manifest_sha256") != digest:
        return ["the evaluation corpus changed since the baseline was frozen — re-freeze it in a reviewed "
                "commit rather than comparing different corpora"]
    problems = []
    for sc, old in sorted(frozen.get("per_sc", {}).items()):
        new = current.get(sc)
        if new is None:
            problems.append(f"SC {sc}: no longer measured")
            continue
        if new["fp"] > old["fp"]:
            problems.append(f"SC {sc}: false positives {old['fp']} -> {new['fp']}")
        if old.get("recall") is not None and (new.get("recall") is None or new["recall"] < old["recall"] - 1e-9):
            problems.append(f"SC {sc}: recall {old['recall']:.3f} -> {new.get('recall')}")
        if old.get("precision") is not None and new.get("precision") is not None \
                and new["precision"] < old["precision"] - 1e-9:
            problems.append(f"SC {sc}: precision {old['precision']:.3f} -> {new['precision']:.3f}")
    return problems


def render(per_sc: dict) -> str:
    from verity.standards import coverage_summary

    def pct(x):
        return "—" if x is None else f"{100 * x:.0f}%"

    lines = ["| SC | TP | FN | FP | TN | needs-review | precision | recall | F1 |",
             "|---|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for sc, s in per_sc.items():
        lines.append(f"| {sc} | {s['tp']} | {s['fn']} | {s['fp']} | {s['tn']} | {s['review']} | "
                     f"{pct(s['precision'])} | {pct(s['recall'])} | {pct(s['f1'])} |")
    cov = coverage_summary(("A", "AA"))
    lines += ["", f"**Coverage (WCAG 2.2 A + AA):** {cov['attempted']}/{cov['criteria']} criteria attempted "
              f"({cov['attempted_share']:.0%}): {cov['by_method']['deterministic']} decided by Verity's own "
              f"measurement, {cov['by_method']['automated-partial']} by automated rules (a pass still needs a "
              f"human), {cov['by_method']['manual']} not attempted: {', '.join(cov['not_attempted'])}."]
    return "\n".join(lines)


# --- running the corpus (needs the worker) -------------------------------------------

async def _scan(path: Path, timeout: float) -> list[dict]:
    from verity.orchestrator.main import scan_url

    report = await scan_url(path.as_uri(), timeout=timeout)
    return [json.loads(f.model_dump_json()) for f in report.findings]


def run_corpus(timeout: float = 120.0) -> tuple[list[Label], dict[str, list[dict]]]:
    from eval.inject.aria_misuse import INJECTORS

    labels = list(FIXTURE_LABELS)
    pages = sorted({x.page for x in FIXTURE_LABELS} | set(EXHAUSTIVE))
    findings: dict[str, list[dict]] = {}
    for page in pages:
        findings[page] = asyncio.run(_scan(FIXTURES / page, timeout))
    with tempfile.TemporaryDirectory() as tmp:
        for i, (fixture, injector, selector, sc, target) in enumerate(MISUSE_LABELS):
            key = f"misuse:{i}:{injector}:{fixture}"
            variant = Path(tmp) / f"{i:02d}-{Path(fixture).name}"
            variant.write_text(INJECTORS[injector].inject((FIXTURES / fixture).read_text(encoding="utf-8"),
                                                          selector), encoding="utf-8")
            findings[key] = asyncio.run(_scan(variant, timeout))
            labels.append(Label(key, sc, target, "fail"))
    return labels, findings


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Per-SC precision/recall on the labelled corpus")
    p.add_argument("--freeze", metavar="VERSION")
    p.add_argument("--check", metavar="VERSION")
    p.add_argument("--out", type=Path)
    args = p.parse_args(argv)

    labels, findings = run_corpus()
    per_sc = score(labels, findings, EXHAUSTIVE)
    text = render(per_sc)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    digest = manifest_digest()
    if args.freeze:
        print(f"frozen: {freeze(per_sc, args.freeze, digest=digest)}")
    if args.check:
        frozen = json.loads((BASELINES / f"{args.check}.json").read_text(encoding="utf-8"))
        problems = compare_to_baseline(per_sc, frozen, digest=digest)
        for line in problems:
            print("REGRESSION:", line)
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
