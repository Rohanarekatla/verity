"""
Verity vs axe-core, Lighthouse, Pa11y and IBM Equal Access — scored against ground truth.

BC-C2 in docs/execution-plan.md: "a reproducible, honest benchmark". Every
tool runs on the same pages, served over HTTP (Lighthouse refuses file://),
and every finding is resolved to the real DOM element it names (CSS selector
or XPath) before it is credited. Only findings on the criterion under test
count — a landmark best-practice rule firing on a keyboard trap is not
"catching the trap", and a target-size finding on a clean widget is not a
false alarm about its keyboard behaviour.

Two parts, both with known answers:

  contrast   text over CSS images/gradients (the case axe marks `incomplete`)
             from eval/contrast_precision.py, plus a solid-background control
             set every tool should get right. Truth = WCAG worst-case ratio.
  keyboard   fixtures with one known keyboard/widget defect each, and clean
             twins (APG-correct widgets, an iframe embed, a :focus-within ring).
             SCs under test: 2.1.1, 2.1.2, 2.4.3, 2.4.7, 4.1.2.

    cd node-worker && npm run build && cd ..
    uv run python eval/benchmark/benchmark.py            # all tools
    uv run python eval/benchmark/benchmark.py verity axe # a subset

First run installs the pinned competitor versions into eval/benchmark/work/
(git-ignored). Results from 2026-10-19: docs/measurements/benchmark-2026-10-19.md.
"""

from __future__ import annotations

import glob
import http.server
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORK = HERE / "work"
SITE = WORK / "site"
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}/"
sys.path.insert(0, str(REPO))

from eval.contrast_precision import FONTS, _hex, _ratio, build  # noqa: E402

PINNED = ["lighthouse@12.8.2", "pa11y@8.0.0", "accessibility-checker@4.0.34"]
CONTRAST_PAGES = ["corpus-101.html", "corpus-102.html", "control-solid.html"]
KEYBOARD_PAGES = {  # page -> (defective target ids, clean target ids)
    "keyboard-trap.html": (["trap"], []),
    "keyboard-unreachable.html": (["stranded"], []),
    "keyboard-positive-tabindex.html": (["jumped"], []),
    "keyboard-focus-within.html": (["bare"], ["wrapped"]),
    "apg/disclosure-fail.html": (["faq-1"], []),
    "apg/menu-button-fail.html": (["actions"], []),
    "apg/tablist-fail.html": (["tabs"], []),
    "apg/disclosure-pass.html": ([], ["faq-1"]),
    "apg/menu-button-pass.html": ([], ["actions"]),
    "apg/tablist-pass.html": ([], ["tabs"]),
    "keyboard-tablist.html": ([], ["tab-1"]),
    "keyboard-iframe.html": ([], ["player", "before", "after"]),
}
KEYBOARD_SC = {"2.1.1", "2.1.2", "2.4.3", "2.4.7", "4.1.2"}
# IBM rule -> SC for the rules relevant here (IBM Equal Access rule docs).
IBM_SC = {"aria_keyboard_handler_exists": ["2.1.1"], "widget_tabbable_exists": ["2.1.1"],
          "style_focus_visible": ["2.4.7"], "element_tabbable_visible": ["2.4.7"],
          "element_tabbable_role_valid": ["4.1.2"], "aria_widget_labelled": ["4.1.2"],
          "input_label_visible": ["2.4.6"], "target_spacing_sufficient": ["2.5.8"]}


# --- setup --------------------------------------------------------------------

def chrome_path() -> str:
    return subprocess.run(
        ["node", "-e", "console.log(require('playwright').chromium.executablePath())"],
        cwd=REPO / "node-worker", capture_output=True, text=True, check=True,
    ).stdout.strip()


def install_tools() -> None:
    if (WORK / "node_modules" / ".bin" / "achecker").exists():
        return
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "package.json").write_text('{"private": true}')
    subprocess.run(["npm", "i", "--no-audit", "--no-fund", *PINNED], cwd=WORK, check=True)


def build_site() -> dict:
    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(REPO / "data" / "fixtures", SITE)
    truth: dict = {}
    for seed in (101, 102):
        page, cases = build(120, seed)
        (SITE / f"corpus-{seed}.html").write_text(page, encoding="utf-8")
        truth[f"corpus-{seed}.html"] = {c["id"]: c for c in cases}
    rnd, html, ctrl = random.Random(7), [], {}
    for i in range(60):
        fg = tuple(rnd.randint(0, 255) for _ in range(3))
        bg = tuple(rnd.randint(0, 255) for _ in range(3))
        size, weight = FONTS[i % len(FONTS)]
        r = _ratio(fg, bg)
        large = size >= 24 or (size >= 18.66 and weight >= 700)
        ctrl[f"s{i}"] = {"id": f"s{i}", "truth": "pass" if r >= (3.0 if large else 4.5) else "fail"}
        html.append(f'<p id="s{i}" style="display:inline-block;margin:4px;padding:8px 12px;color:{_hex(fg)};'
                    f'background-color:{_hex(bg)};font-size:{size}px;font-weight:{weight}">'
                    f'Sample text {i} Hamburgefonstiv</p>')
    (SITE / "control-solid.html").write_text(
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Solid control</title></head>'
        '<body><main><h1>Control</h1>' + "\n".join(html) + "</main></body></html>", encoding="utf-8")
    truth["control-solid.html"] = ctrl
    return truth


def serve() -> None:
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


# --- tools ----------------------------------------------------------------------

def run_verity(urls, env):
    out = {}
    for u in urls:
        t0 = time.time()
        subprocess.run([sys.executable, "-m", "verity.cli", "scan", u, "-o", str(WORK / "verity.json")],
                       cwd=REPO, capture_output=True)
        items = []
        for f in json.load(open(WORK / "verity.json"))["findings"]:
            if f["outcome"] == "pass" or not f["evidence"].get("dom_selector"):
                continue
            level = "fail" if f["provenance"] == "authoritative" else "review"
            sels = [f["evidence"]["dom_selector"]]
            cv = f["evidence"].get("computed_values") or {}
            for key in ("unreachable", "no_indicator"):
                sels += cv.get(key) or []
            sels += [d["selector"] for d in cv.get("positive_tabindex") or []]
            items += [{"sel": s, "level": level, "rule": f["sc"]["id"]} for s in sels]
        out[u] = {"secs": time.time() - t0, "items": items}
    return out


def run_axe(urls, env):
    p = subprocess.run(["node", str(HERE / "axe_run.mjs"), *urls], capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def run_lighthouse(urls, env):
    out = {}
    for u in urls:
        t0 = time.time()
        subprocess.run(["npx", "lighthouse", u, "--only-categories=accessibility", "--output=json",
                        "--output-path=lh.json", "--chrome-flags=--headless=new", "--quiet"],
                       cwd=WORK, env=env, capture_output=True)
        r = json.load(open(WORK / "lh.json"))
        items = [{"sel": it["node"]["selector"], "level": "fail", "rule": aid}
                 for aid, a in r["audits"].items() if a.get("score") == 0
                 for it in (a.get("details") or {}).get("items", []) if (it.get("node") or {}).get("selector")]
        out[u] = {"secs": time.time() - t0, "items": items}
    return out


def run_pa11y(urls, env):
    cfg = WORK / "pa11y.json"
    cfg.write_text(json.dumps({"chromeLaunchConfig": {"executablePath": env["CHROME_PATH"], "args": ["--no-sandbox"]}}))
    out = {}
    for u in urls:
        t0 = time.time()
        p = subprocess.run(["npx", "pa11y", "--config", str(cfg), "--reporter", "json", "--include-warnings",
                            "--include-notices", "--timeout", "120000", u], cwd=WORK, env=env,
                           capture_output=True, text=True)
        try:
            res = json.loads(p.stdout or "[]")
        except json.JSONDecodeError:
            res = []
        out[u] = {"secs": time.time() - t0,
                  "items": [{"sel": x["selector"], "level": "fail" if x["type"] == "error" else "review",
                             "rule": x["code"]} for x in res if x.get("selector")]}
    return out


def run_ibm(urls, env):
    (WORK / ".achecker.yml").write_text(
        "ruleArchive: latest\npolicies:\n  - WCAG_2_2\nfailLevels:\n  - violation\n"
        "reportLevels:\n  - violation\n  - potentialviolation\noutputFormat:\n  - json\n"
        "outputFolder: ibm-results\n")
    out = {}
    for u in urls:
        shutil.rmtree(WORK / "ibm-results", ignore_errors=True)
        t0 = time.time()
        subprocess.run(["npx", "achecker", u], cwd=WORK, env=env, capture_output=True)
        secs = time.time() - t0
        items = []
        for f in glob.glob(str(WORK / "ibm-results/**/*.json"), recursive=True):
            if "summary" in f:
                continue
            for x in json.load(open(f))["results"]:
                kind, outcome = x["value"]
                if kind == "VIOLATION" and outcome != "PASS":
                    items.append({"sel": x["path"]["dom"], "level": "fail" if outcome == "FAIL" else "review",
                                  "rule": x["ruleId"]})
        out[u] = {"secs": secs, "items": items}
    return out


TOOLS = {"verity": run_verity, "axe": run_axe, "lighthouse": run_lighthouse, "pa11y": run_pa11y, "ibm": run_ibm}


# --- scoring --------------------------------------------------------------------

def axe_sc() -> dict:
    p = subprocess.run(["node", "-e", """
const axe = require('axe-core'); const m = {};
for (const r of axe.getRules()) m[r.ruleId] = r.tags.filter(t => /^wcag\\d{3,4}$/.test(t))
  .map(t => { const d = t.slice(4); return d[0] + '.' + d[1] + '.' + d.slice(2); });
console.log(JSON.stringify(m));"""], cwd=REPO / "node-worker", capture_output=True, text=True, check=True)
    return json.loads(p.stdout)


def scorer(raw, resolved, refs, axe_map):
    def is_contrast(tool, rule):
        return {"axe": rule == "color-contrast", "lighthouse": rule == "color-contrast",
                "pa11y": "1_4_3" in rule, "ibm": rule == "text_contrast_sufficient",
                "verity": rule == "1.4.3"}[tool]

    def sc_of(tool, rule):
        if tool in ("axe", "lighthouse"):
            return set(axe_map.get(rule, []))
        if tool == "pa11y":
            m = re.search(r"Guideline\d_\d+\.(\d)_(\d+)_(\d+)", rule)
            return {f"{m.group(1)}.{m.group(2)}.{m.group(3)}"} if m else set()
        if tool == "ibm":
            return set(IBM_SC.get(rule, []))
        return {rule}

    def attributed(tool, page, targets, contrast):
        u = BASE + page
        ids_of = dict(zip(refs[u], resolved[u]))
        best = {}
        for it in raw[tool][u]["items"]:
            if contrast and not is_contrast(tool, it["rule"]):
                continue
            if not contrast and not (sc_of(tool, it["rule"]) & KEYBOARD_SC):
                continue
            for tid in ids_of.get(it["sel"], []):
                if tid in targets:
                    if best.get(tid) != "fail":
                        best[tid] = it["level"]
                    break
        return best
    return attributed


def report(raw, truth, attributed) -> str:
    lines = ["## Contrast — truth is the WCAG worst-case ratio", "",
             "| Tool | Set | True fails | Caught | Sent to review | Missed silently | False fails |",
             "|---|---|---|---|---|---|---|"]
    for tool in raw:
        for label, pages in (("image / gradient", ["corpus-101.html", "corpus-102.html"]),
                             ("solid (control)", ["control-solid.html"])):
            tf = caught = review = missed = ff = 0
            for page in pages:
                best = attributed(tool, page, set(truth[page]), True)
                for cid, c in truth[page].items():
                    lvl = best.get(cid)
                    if c["truth"] == "fail":
                        tf += 1
                        caught += lvl == "fail"
                        review += lvl == "review"
                        missed += lvl is None
                    else:
                        ff += lvl == "fail"
            lines.append(f"| {tool} | {label} | {tf} | {caught} | {review} | {missed} | {ff} |")
    lines += ["", "## Keyboard & widgets — one known defect per page, plus clean twins", "",
              "| Tool | Defects caught | Sent to review | False alarms on clean widgets |", "|---|---|---|---|"]
    for tool in raw:
        caught = review = n_def = fa = n_clean = 0
        for page, (bad, good) in KEYBOARD_PAGES.items():
            best = attributed(tool, page, set(bad) | set(good), False)
            for t in bad:
                n_def += 1
                caught += best.get(t) == "fail"
                review += best.get(t) == "review"
            for t in good:
                n_clean += 1
                fa += best.get(t) == "fail"
        lines.append(f"| {tool} | {caught} / {n_def} | {review} | {fa} / {n_clean} |")
    lines += ["", "## Time (seconds)", "", "| Tool | All pages | 120-case corpus page | Small widget page |",
              "|---|---|---|---|"]
    for tool in raw:
        s = {u[len(BASE):]: v["secs"] for u, v in raw[tool].items()}
        lines.append(f"| {tool} | {sum(s.values()):.1f} | {s['corpus-101.html']:.1f} | "
                     f"{s['apg/disclosure-pass.html']:.1f} |")
    return "\n".join(lines)


def main() -> int:
    tools = sys.argv[1:] or list(TOOLS)
    install_tools()
    env = {**os.environ, "CHROME_PATH": chrome_path()}
    env["PUPPETEER_EXECUTABLE_PATH"] = env["CHROME_PATH"]
    truth = build_site()
    serve()
    urls = [BASE + p for p in CONTRAST_PAGES + list(KEYBOARD_PAGES)]
    raw = {}
    for name in tools:
        print(f"running {name} …", file=sys.stderr, flush=True)
        raw[name] = TOOLS[name](urls, env)
    refs = {u: sorted({i["sel"] for t in raw.values() for i in t[u]["items"]}) for u in urls}
    (WORK / "refs.json").write_text(json.dumps(refs))
    subprocess.run(["node", str(HERE / "resolve.mjs"), str(WORK / "refs.json"), str(WORK / "resolved.json")],
                   check=True)
    resolved = json.loads((WORK / "resolved.json").read_text())
    (WORK / "raw.json").write_text(json.dumps(raw))
    print(report(raw, truth, scorer(raw, resolved, refs, axe_sc())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
