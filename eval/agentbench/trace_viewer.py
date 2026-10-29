"""
A12.3′ — the trace viewer.

A benchmark number is only trustworthy if you can see how it was produced. The
runner (A12.1′) writes, for every measured episode, the full trace: the goal,
and for each step the *exact accessibility tree the agent saw* and the action it
chose from it. This replays that trace step by step, so "the tree agent failed
`click-button` under `strip_name`" can be inspected rather than taken on faith:
you read the tree, see the button has no name, and watch the agent either
`report_infeasible` or click the wrong thing.

Two renderings from the one trace file:

- **Terminal** (`render_text`) — the default; the goal, then each step as the
  AXTree followed by the action and its result. For a quick look from the CLI.
- **HTML** (`render_html`) — a self-contained, theme-aware page with each step
  collapsible and the tree in a monospace block, for sharing a single
  interesting episode.

This reads traces; it computes nothing and judges nothing. Success is the
runner's record, not something re-derived here.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Optional


def load_trace(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_trace(traces_dir: Path, episode_id: str) -> Optional[Path]:
    """Locate a trace by episode id, matching the runner's filename sanitising."""
    import re

    safe = re.sub(r"[^0-9A-Za-z._-]+", "_", episode_id)
    candidate = Path(traces_dir) / f"{safe}.json"
    if candidate.exists():
        return candidate
    # Fall back to reading ids out of the files (in case the id had odd chars).
    for p in sorted(Path(traces_dir).glob("*.json")):
        try:
            if json.loads(p.read_text(encoding="utf-8")).get("episode_id") == episode_id:
                return p
        except (ValueError, OSError):
            continue
    return None


def list_traces(traces_dir: Path) -> list[dict]:
    """A one-line summary per trace in a directory, for picking one to open."""
    out = []
    for p in sorted(Path(traces_dir).glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        out.append({
            "episode_id": t.get("episode_id", p.stem),
            "task_id": t.get("task_id"), "defect": t.get("defect"),
            "model": t.get("model_label") or t.get("model"),
            "steps": len(t.get("steps", [])),
            "reward": t.get("reward"), "done": t.get("done"),
            "infeasible": t.get("infeasible"), "path": str(p),
        })
    return out


def _verdict(trace: dict) -> str:
    if trace.get("infeasible"):
        return "report_infeasible"
    return "success" if (trace.get("reward") or 0) > 0 else "failure"


# -- terminal -----------------------------------------------------------------

def render_text(trace: dict) -> str:
    """The episode as plain text, ready for a terminal."""
    lines: list[str] = []
    head = (f"episode {trace.get('episode_id','?')}  "
            f"[{trace.get('agent','?')} · {trace.get('model_label') or trace.get('model','?')}]")
    lines.append(head)
    lines.append("=" * len(head))
    lines.append(f"task:    {trace.get('task_id')}   defect: {trace.get('defect')}   trial: {trace.get('trial')}")
    lines.append(f"goal:    {trace.get('goal')}")
    verdict = _verdict(trace)
    lines.append(f"verdict: {verdict}   reward={trace.get('reward')}   "
                 f"steps={len(trace.get('steps', []))}   {trace.get('seconds', 0):.2f}s")
    if trace.get("parse_failures"):
        lines.append(f"         ({trace['parse_failures']} unparseable model replies)")
    lines.append("")
    for s in trace.get("steps", []):
        lines.append(f"── step {s['n']} ─────────────────────────────────────────")
        lines.append("  accessibility tree the agent saw:")
        obs = s.get("observation") or "(empty tree)"
        for line in obs.splitlines():
            lines.append("    " + line)
        mark = "ok" if s.get("ok") else "FAIL"
        lines.append(f"  → action: {s.get('action')}   [{mark}]")
        if s.get("error"):
            lines.append(f"    error: {s['error']}")
        lines.append("")
    return "\n".join(lines)


# -- html ---------------------------------------------------------------------

_HTML_CSS = """
:root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#e3e3e3; --head:#f5f5f5;
        --tree:#f7f7f8; --good:#0a7d32; --bad:#c0392b; --accent:#2b6cb0; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg:#15171a; --fg:#e8e8e8; --muted:#9aa0a6; --line:#2c2f34; --head:#1e2126;
  --tree:#1b1e23; --good:#4ade80; --bad:#f87171; --accent:#63b3ed; } }
:root[data-theme="dark"] {
  --bg:#15171a; --fg:#e8e8e8; --muted:#9aa0a6; --line:#2c2f34; --head:#1e2126;
  --tree:#1b1e23; --good:#4ade80; --bad:#f87171; --accent:#63b3ed; }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); margin:0;
       font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }
main { max-width:860px; margin:0 auto; padding:32px 16px 64px; }
h1 { font-size:22px; margin:0 0 4px; }
.meta { color:var(--muted); margin:2px 0; }
.verdict { display:inline-block; padding:2px 10px; border-radius:4px; font-weight:600; font-size:13px; }
.v-success { background:color-mix(in srgb, var(--good) 20%, transparent); color:var(--good); }
.v-failure { background:color-mix(in srgb, var(--bad) 20%, transparent); color:var(--bad); }
.v-report_infeasible { background:color-mix(in srgb, var(--accent) 20%, transparent); color:var(--accent); }
details { border:1px solid var(--line); border-radius:6px; margin:10px 0; overflow:hidden; }
summary { cursor:pointer; padding:10px 14px; background:var(--head); font-weight:600;
          list-style:none; display:flex; justify-content:space-between; gap:12px; }
summary::-webkit-details-marker { display:none; }
.step-body { padding:12px 14px; }
.tree { background:var(--tree); border-radius:5px; padding:10px 12px; margin:0 0 10px;
        font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; white-space:pre; overflow-x:auto; }
.action { font:13px ui-monospace,Menlo,monospace; }
.ok { color:var(--good); } .fail { color:var(--bad); }
.err { color:var(--bad); font:12px ui-monospace,Menlo,monospace; margin-top:6px; }
"""


def render_html(trace: dict) -> str:
    """A self-contained HTML replay of one episode."""
    e = html.escape
    verdict = _verdict(trace)
    steps_html = []
    for s in trace.get("steps", []):
        mark = ("<span class='ok'>ok</span>" if s.get("ok")
                else "<span class='fail'>FAIL</span>")
        err = f"<div class='err'>{e(str(s['error']))}</div>" if s.get("error") else ""
        steps_html.append(
            f"<details open><summary><span>step {s['n']}</span>"
            f"<span class='action'>{e(str(s.get('action')))} &nbsp;[{mark}]</span></summary>"
            f"<div class='step-body'>"
            f"<div class='tree'>{e(s.get('observation') or '(empty tree)')}</div>"
            f"{err}</div></details>"
        )
    model = trace.get("model_label") or trace.get("model") or "?"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(trace.get('episode_id','trace'))}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<main>
<h1>{e(trace.get('task_id','?'))} · {e(str(trace.get('defect')))}</h1>
<p class="meta">{e(trace.get('agent','?'))} · {e(str(model))} · trial {e(str(trace.get('trial')))}</p>
<p class="meta">goal: {e(str(trace.get('goal')))}</p>
<p><span class="verdict v-{e(verdict)}">{e(verdict)}</span>
   <span class="meta">reward {e(str(trace.get('reward')))} · {len(trace.get('steps', []))} steps ·
   {trace.get('seconds', 0):.2f}s</span></p>
{''.join(steps_html)}
</main>
</body>
</html>
"""


# -- CLI ----------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Replay an AgentBench episode trace.")
    ap.add_argument("target", help="a trace .json file, or a traces/ directory")
    ap.add_argument("--episode", help="when target is a directory: the episode id to open")
    ap.add_argument("--list", action="store_true", help="list the traces in a directory")
    ap.add_argument("--html", metavar="OUT", help="write an HTML replay to OUT instead of printing")
    args = ap.parse_args(argv)

    target = Path(args.target)
    if target.is_dir():
        if args.list or not args.episode:
            for t in list_traces(target):
                flag = "infeasible" if t["infeasible"] else ("ok" if (t["reward"] or 0) > 0 else "fail")
                print(f"{t['episode_id']:<55}  {t['steps']:>2} steps  {flag}")
            return 0
        found = find_trace(target, args.episode)
        if not found:
            print(f"no trace for episode {args.episode!r} under {target}", file=sys.stderr)
            return 2
        target = found

    trace = load_trace(target)
    if args.html:
        Path(args.html).write_text(render_html(trace), encoding="utf-8")
        print(f"wrote {args.html}")
    else:
        print(render_text(trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
