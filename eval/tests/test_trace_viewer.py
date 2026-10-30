"""
A12.3′ — the trace viewer.

Proves it replays an episode from the trace the runner writes: the terminal
rendering shows the AXTree the agent saw and every action with its result; the
HTML rendering is self-contained; traces are found by episode id and listed from
a directory; and the CLI prints, writes HTML, and lists.
"""

import json

from eval.agentbench.trace_viewer import (
    find_trace,
    list_traces,
    main,
    render_html,
    render_text,
)


def _trace(episode_id="tree|m|click-button|strip_name|t0", reward=0.0, infeasible=True):
    return {
        "episode_id": episode_id, "task_id": "click-button", "agent": "tree",
        "model_label": "m", "provider": "fake", "model": "fake-1",
        "defect": "strip_name", "trial": 0, "goal": "Click the Submit button.",
        "done": True, "reward": reward, "seconds": 0.42, "infeasible": infeasible,
        "parse_failures": 0,
        "steps": [
            {"n": 1, "observation": '[1] button\n[2] textbox "Email"',
             "action": "report_infeasible", "ok": True, "error": None},
        ],
    }


def test_text_render_shows_tree_action_and_verdict():
    out = render_text(_trace())
    assert "goal:    Click the Submit button." in out
    assert "verdict: report_infeasible" in out
    assert '[1] button' in out                 # the tree the agent saw
    assert "→ action: report_infeasible" in out


def test_text_verdict_is_success_on_positive_reward():
    out = render_text(_trace(reward=1.0, infeasible=False))
    assert "verdict: success" in out


def test_html_render_is_self_contained():
    out = render_html(_trace())
    assert out.startswith("<!doctype html>")
    assert "prefers-color-scheme: dark" in out
    assert "report_infeasible" in out
    assert "http://" not in out and "https://" not in out


def test_html_escapes_tree_content():
    t = _trace()
    t["steps"][0]["observation"] = '<script>alert(1)</script>'
    out = render_html(t)
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_find_and_list_traces(tmp_path):
    traces = tmp_path / "traces"
    traces.mkdir()
    t = _trace()
    from eval.agentbench.runner import _safe_name
    (traces / f"{_safe_name(t['episode_id'])}.json").write_text(json.dumps(t), encoding="utf-8")

    found = find_trace(traces, t["episode_id"])
    assert found is not None and json.loads(found.read_text())["task_id"] == "click-button"

    listed = list_traces(traces)
    assert len(listed) == 1 and listed[0]["episode_id"] == t["episode_id"]
    assert listed[0]["steps"] == 1


def test_cli_prints_and_writes_html(tmp_path, capsys):
    path = tmp_path / "t.json"
    path.write_text(json.dumps(_trace()), encoding="utf-8")

    assert main([str(path)]) == 0
    assert "verdict: report_infeasible" in capsys.readouterr().out

    out_html = tmp_path / "replay.html"
    assert main([str(path), "--html", str(out_html)]) == 0
    assert out_html.exists() and out_html.read_text().startswith("<!doctype html>")


def test_cli_lists_a_directory(tmp_path, capsys):
    traces = tmp_path / "traces"
    traces.mkdir()
    from eval.agentbench.runner import _safe_name
    t = _trace()
    (traces / f"{_safe_name(t['episode_id'])}.json").write_text(json.dumps(t), encoding="utf-8")
    assert main([str(traces), "--list"]) == 0
    out = capsys.readouterr().out
    assert "click-button" in out and "infeasible" in out
