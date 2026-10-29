"""
A12.2′ — the results store and dashboards.

The runner (A12.1′) writes `records.jsonl` — the canonical, append-only,
resumable log that `analysis.py` reads and that the pre-registration pins as the
contract. This module adds the two things a results log is not:

1. **A columnar store (Parquet).** The same episodes, written once the run is
   complete, in a format a notebook / BI tool / `pandas` reads a column at a
   time. JSON lines stays the source of truth (it is what the pre-registered
   analysis consumes); Parquet is the derived, query-friendly copy. The
   round-trip is lossless and tested, so the two never disagree.

2. **Dashboards: success by defect × agent × model.** A Markdown table for the
   results doc and a self-contained HTML page for a glance. Both read straight
   from the records and the pre-registered `analysis.py` functions — the Wilson
   interval per cell, the paired clean-vs-defect gap — so a dashboard can never
   quote a number the confirmatory analysis would not.

Nothing here is computed *during* a run. A dashboard of success rates is exactly
the "peeking" the pre-registration forbids mid-run (§9); these functions are a
post-run artifact, run against a finished `records.jsonl`.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from eval.agentbench.analysis import (
    CLEAN,
    EpisodeRecord,
    pair_episodes,
    paired_effect,
    wilson,
)

# The columns the Parquet store holds, in order. Kept explicit (not reflected
# off the model) so a field added to EpisodeRecord is a deliberate schema change
# here, not a silent one.
_COLUMNS = (
    "episode_id", "task_id", "app", "defect", "defect_family", "agent",
    "provider", "model", "trial", "seed", "outcome", "excluded_reason",
    "steps", "input_tokens", "output_tokens", "cache_read_tokens",
    "cache_write_tokens", "cost_usd",
)


def write_parquet(records: list[EpisodeRecord], path: Path) -> Path:
    """Write the episodes to a Parquet file (columnar). Returns the path."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = {c: [getattr(r, c) for r in records] for c in _COLUMNS}
    pq.write_table(pa.table(cols), path)
    return path


def read_parquet(path: Path) -> list[EpisodeRecord]:
    """Read episodes back from Parquet into the same records the runner wrote."""
    import pyarrow.parquet as pq

    table = pq.read_table(Path(path))
    rows = table.to_pylist()
    return [EpisodeRecord.model_validate(row) for row in rows]


# -- the success matrix -------------------------------------------------------

@dataclass
class CellRow:
    """One (agent × model × defect) cell of the dashboard."""

    agent: str
    model: str
    defect: str
    family: Optional[str]
    episodes: int
    excluded: int
    successes: int
    usable: int

    @property
    def rate(self) -> float:
        return self.successes / self.usable if self.usable else float("nan")

    @property
    def wilson_ci(self) -> tuple[float, float, float]:
        return wilson(self.successes, self.usable)


def success_matrix(records: list[EpisodeRecord]) -> list[CellRow]:
    """
    Success per (agent, model, defect), with the episode and exclusion counts.
    Sorted so the clean control sits first within each (agent, model) block,
    making the clean-vs-defect contrast easy to read down the column.
    """
    cells: dict[tuple, list[EpisodeRecord]] = {}
    for r in records:
        cells.setdefault((r.agent, r.model, r.defect), []).append(r)
    rows: list[CellRow] = []
    for (agent, model, defect), rs in cells.items():
        usable = [r for r in rs if r.usable]
        rows.append(CellRow(
            agent=agent, model=model, defect=defect,
            family=next((r.defect_family for r in rs if r.defect_family), None),
            episodes=len(rs), excluded=len(rs) - len(usable),
            successes=sum(1 for r in usable if r.outcome == "success"), usable=len(usable),
        ))
    rows.sort(key=lambda c: (c.agent, c.model, c.defect != CLEAN, c.defect))
    return rows


def defect_gaps(records: list[EpisodeRecord]) -> list[dict]:
    """
    The headline of results-v1: per (agent × model × defect) the paired
    clean-vs-defect success gap, from the pre-registered `paired_effect`. This
    is a post-run read of the confirmatory analysis, not a new statistic.
    """
    agents = sorted({r.agent for r in records})
    models = sorted({r.model for r in records})
    defects = sorted({r.defect for r in records if r.defect != CLEAN})
    out: list[dict] = []
    for agent in agents:
        for model in models:
            for defect in defects:
                pairs, dropped = pair_episodes(records, defect=defect, agent=agent, model=model)
                if not pairs:
                    continue
                eff = paired_effect(pairs, dropped)
                out.append({"agent": agent, "model": model, "defect": defect, **eff})
    return out


# -- dashboards ---------------------------------------------------------------

def _pct(x: float) -> str:
    return "—" if x != x else f"{x:.0%}"  # x != x catches NaN


def render_markdown_dashboard(records: list[EpisodeRecord], *, title: str = "AgentBench results v1") -> str:
    """The dashboard for `docs/agentbench/results-v1.md`."""
    rows = success_matrix(records)
    gaps = defect_gaps(records)
    excluded = sum(c.excluded for c in rows)
    lines = [f"# {title}", ""]
    lines.append(f"**Episodes:** {sum(c.episodes for c in rows)}  ·  "
                 f"**excluded:** {excluded}  ·  "
                 f"**cells:** {len(rows)}")
    lines.append("")
    lines.append("## Success by agent × model × defect")
    lines.append("")
    lines.append("| agent | model | defect | family | n | excl | success | 95% CI |")
    lines.append("|---|---|---|---|--:|--:|--:|---|")
    for c in rows:
        _, lo, hi = c.wilson_ci
        lines.append(f"| {c.agent} | {c.model} | {c.defect} | {c.family or '—'} | "
                     f"{c.usable} | {c.excluded} | {_pct(c.rate)} | "
                     f"[{_pct(lo)}, {_pct(hi)}] |")
    lines.append("")
    lines.append("## Clean vs defect — paired effect (pre-registered)")
    lines.append("")
    lines.append("| agent | model | defect | pairs | clean | defect | Δ (clean−defect) | 95% CI | McNemar p |")
    lines.append("|---|---|---|--:|--:|--:|--:|---|--:|")
    for g in gaps:
        clo = g["clean_success"]
        dlo = g["defect_success"]
        lo, hi = g["diff_ci"]
        lines.append(f"| {g['agent']} | {g['model']} | {g['defect']} | {g['pairs']} | "
                     f"{_pct(clo[0])} | {_pct(dlo[0])} | {g['diff']:+.0%} | "
                     f"[{lo:+.0%}, {hi:+.0%}] | {g['mcnemar_p']:.3f} |")
    lines.append("")
    lines.append("> Effect = success(clean) − success(defect) on paired episodes. A positive Δ "
                 "means the defect reduced success. Significance is Holm-adjusted within the H1 "
                 "family in `analysis.py`; nulls are reported with their intervals, not dropped.")
    return "\n".join(lines) + "\n"


_HTML_CSS = """
:root {
  --bg: #ffffff; --fg: #1a1a1a; --muted: #666; --line: #e3e3e3;
  --head: #f5f5f5; --good: #0a7d32; --bad: #c0392b; --accent: #2b6cb0;
}
:root:not([data-theme="light"]) { }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #15171a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f34;
    --head: #1e2126; --good: #4ade80; --bad: #f87171; --accent: #63b3ed;
  }
}
:root[data-theme="dark"] {
  --bg: #15171a; --fg: #e8e8e8; --muted: #9aa0a6; --line: #2c2f34;
  --head: #1e2126; --good: #4ade80; --bad: #f87171; --accent: #63b3ed;
}
* { box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); margin: 0;
       font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
main { max-width: 1000px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 32px 0 12px; }
.meta { color: var(--muted); margin-bottom: 8px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0 24px; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); }
th { background: var(--head); font-weight: 600; position: sticky; top: 0; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.bar { display: inline-block; height: 9px; border-radius: 2px; background: var(--accent); vertical-align: middle; }
.pos { color: var(--bad); font-weight: 600; }   /* defect hurt: bad for the agent */
.neg { color: var(--good); }
.note { color: var(--muted); font-size: 13px; margin-top: 4px; }
"""


def render_html_dashboard(records: list[EpisodeRecord], *, title: str = "AgentBench results v1") -> str:
    """A self-contained HTML dashboard — one file, theme-aware, no network."""
    rows = success_matrix(records)
    gaps = defect_gaps(records)
    e = html.escape

    def cell_rows() -> str:
        out = []
        for c in rows:
            p, lo, hi = c.wilson_ci
            width = 0 if p != p else int(round(p * 120))
            out.append(
                f"<tr><td>{e(c.agent)}</td><td>{e(c.model)}</td><td>{e(c.defect)}</td>"
                f"<td>{e(c.family or '—')}</td><td class='num'>{c.usable}</td>"
                f"<td class='num'>{c.excluded}</td>"
                f"<td class='num'>{_pct(c.rate)} <span class='bar' style='width:{width}px'></span></td>"
                f"<td class='num'>[{_pct(lo)}, {_pct(hi)}]</td></tr>"
            )
        return "\n".join(out)

    def gap_rows() -> str:
        out = []
        for g in gaps:
            lo, hi = g["diff_ci"]
            cls = "pos" if g["diff"] > 0 else "neg"
            out.append(
                f"<tr><td>{e(g['agent'])}</td><td>{e(g['model'])}</td><td>{e(g['defect'])}</td>"
                f"<td class='num'>{g['pairs']}</td>"
                f"<td class='num'>{_pct(g['clean_success'][0])}</td>"
                f"<td class='num'>{_pct(g['defect_success'][0])}</td>"
                f"<td class='num {cls}'>{g['diff']:+.0%}</td>"
                f"<td class='num'>[{lo:+.0%}, {hi:+.0%}]</td>"
                f"<td class='num'>{g['mcnemar_p']:.3f}</td></tr>"
            )
        return "\n".join(out)

    n_ep = sum(c.episodes for c in rows)
    n_excl = sum(c.excluded for c in rows)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<main>
<h1>{e(title)}</h1>
<p class="meta">{n_ep} episodes · {n_excl} excluded · {len(rows)} cells</p>

<h2>Success by agent × model × defect</h2>
<table>
<thead><tr><th>agent</th><th>model</th><th>defect</th><th>family</th>
<th class="num">n</th><th class="num">excl</th><th class="num">success</th>
<th class="num">95% CI</th></tr></thead>
<tbody>
{cell_rows()}
</tbody>
</table>

<h2>Clean vs defect — paired effect (pre-registered)</h2>
<table>
<thead><tr><th>agent</th><th>model</th><th>defect</th><th class="num">pairs</th>
<th class="num">clean</th><th class="num">defect</th><th class="num">Δ</th>
<th class="num">95% CI</th><th class="num">McNemar p</th></tr></thead>
<tbody>
{gap_rows()}
</tbody>
</table>
<p class="note">Δ = success(clean) − success(defect) on paired episodes; a positive Δ (red)
means the defect reduced the agent's success. Significance is Holm-adjusted within H1 in
<code>analysis.py</code>. Null results are shown with their intervals, not dropped.</p>
</main>
</body>
</html>
"""


def build_dashboards(records_path: Path, out_dir: Path, *, title: str = "AgentBench results v1") -> dict:
    """Read `records.jsonl`, write the Parquet store and both dashboards."""
    from eval.agentbench.analysis import load_records

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    records = load_records(Path(records_path))
    parquet = write_parquet(records, out_dir / "results.parquet")
    md = out_dir / "dashboard.md"
    md.write_text(render_markdown_dashboard(records, title=title), encoding="utf-8")
    html_path = out_dir / "dashboard.html"
    html_path.write_text(render_html_dashboard(records, title=title), encoding="utf-8")
    return {"parquet": parquet, "markdown": md, "html": html_path, "episodes": len(records)}
