"""
Contrast precision benchmark — every adjudicated verdict checked against ground truth.

Generates a page of text over CSS-image backgrounds (so axe marks every node
`incomplete` and Verity's pixel adjudicator has to decide), with the true
worst-case ratio and size class known for each, runs the real CLI on it, and
counts every authoritative verdict that contradicts the truth.

Case kinds, cycled:
  0  split gradient — one or two background colours behind the text
  1  fine checkerboard image — both colours sit behind every glyph
  2  pill button on a contrasting page colour — corners must not count
  3  thin (300), small (12–14px), underlined, letter-spaced text

The bar is zero: a false fail costs a user trust, a false pass ships a
barrier. Undecided (`cantTell`) is allowed and reported separately.

    cd node-worker && npm run build && cd ..
    uv run python eval/contrast_precision.py --seed 7 --cases 120

Used in end-to-end hardening on 2026-10-18; results in
docs/measurements/contrast-precision.md.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from verity.agents.contrast import (  # noqa: E402
    calculate_contrast_ratio,
    calculate_relative_luminance,
)

FONTS = [(12, 400), (14, 400), (16, 400), (18, 400), (18.67, 700),
         (20, 700), (24, 400), (28, 400), (32, 700), (16, 700)]


def _hex(c: tuple[int, int, int]) -> str:
    return "#%02x%02x%02x" % c


def _ratio(a, b) -> float:
    return calculate_contrast_ratio(calculate_relative_luminance(*a), calculate_relative_luminance(*b))


def build(n: int, seed: int) -> tuple[str, list[dict]]:
    rnd = random.Random(seed)
    colour = lambda: tuple(rnd.randint(0, 255) for _ in range(3))  # noqa: E731
    cases, html = [], []
    for i in range(n):
        fg, bg1 = colour(), colour()
        size, weight = FONTS[i % len(FONTS)]
        kind = i % 4
        if kind == 0:
            bg2 = bg1 if i % 3 else colour()
            css = f"background-image:linear-gradient(to right,{_hex(bg1)} 0 50%,{_hex(bg2)} 50% 100%)"
        elif kind == 1:
            bg2 = colour()
            svg = (f"<svg xmlns='http://www.w3.org/2000/svg' width='6' height='6'>"
                   f"<rect width='6' height='6' fill='{_hex(bg1)}'/><rect width='3' height='3' fill='{_hex(bg2)}'/>"
                   f"<rect x='3' y='3' width='3' height='3' fill='{_hex(bg2)}'/></svg>")
            css = "background-image:url(data:image/svg+xml," + urllib.parse.quote(svg, safe="") + ")"
        elif kind == 2:
            bg2 = bg1
            css = f"background-image:linear-gradient({_hex(bg1)},{_hex(bg1)});border-radius:999px;padding:10px 22px"
        else:
            bg2 = bg1
            size, weight = 12 + i % 3, 300
            css = (f"background-image:linear-gradient({_hex(bg1)},{_hex(bg1)});"
                   "text-decoration:underline;letter-spacing:.5px")
        worst = min(_ratio(fg, bg1), _ratio(fg, bg2))
        large = size >= 24 or (size >= 18.66 and weight >= 700)
        cases.append({
            "id": f"c{i}", "kind": kind, "worst": worst, "large": large,
            "truth": "pass" if worst >= (3.0 if large else 4.5) else "fail",
        })
        page_bg = "#0b0b0b" if sum(bg1) > 380 else "#fafafa"
        html.append(
            f'<div style="background:{page_bg};padding:6px;display:inline-block">'
            f'<p id="c{i}" style="display:inline-block;margin:0;padding:8px 12px;color:{_hex(fg)};'
            f'font-size:{size}px;font-weight:{weight};{css}">Sample text {i} Hamburgefonstiv</p></div>'
        )
    page = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Contrast precision</title>'
            '<style>body{font-family:sans-serif;background:#fff}</style></head><body><main><h1>Corpus</h1>'
            + "\n".join(html) + "</main></body></html>")
    return page, cases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cases", type=int, default=120)
    args = ap.parse_args()

    page, cases = build(args.cases, args.seed)
    with tempfile.TemporaryDirectory() as tmp:
        html, out = Path(tmp) / "corpus.html", Path(tmp) / "report.json"
        html.write_text(page, encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "verity.cli", "scan", html.as_uri(), "-o", str(out)],
            cwd=REPO, capture_output=True, check=False,
        )
        report = json.loads(out.read_text())

    by_id: dict[str, list[dict]] = {}
    for f in report["findings"]:
        if f["sc"]["id"] == "1.4.3":
            by_id.setdefault((f["evidence"].get("dom_selector") or "").lstrip("#"), []).append(f)

    false_fail = false_pass = decided = undecided = missing = 0
    for c in cases:
        found = by_id.get(c["id"], [])
        if not found:
            missing += 1
            print(f"  NOT REPORTED {c['id']} kind={c['kind']} truth={c['truth']} worst={c['worst']:.2f}")
            continue
        for f in found:
            if f["provenance"] != "authoritative":
                undecided += 1
                continue
            decided += 1
            if f["outcome"] != c["truth"]:
                adj = f["evidence"]["computed_values"].get("contrast_adjudication") or {}
                kind = "FALSE FAIL" if f["outcome"] == "fail" else "FALSE PASS"
                false_fail += kind == "FALSE FAIL"
                false_pass += kind == "FALSE PASS"
                print(f"  {kind} {c['id']} kind={c['kind']} truth worst={c['worst']:.2f} "
                      f"measured={adj.get('worst_case_ratio')} large={c['large']}")

    print(f"seed={args.seed} cases={len(cases)} decided={decided} undecided={undecided} "
          f"not_reported={missing} FALSE_FAIL={false_fail} FALSE_PASS={false_pass}")
    return 1 if (false_fail or false_pass or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
