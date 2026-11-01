"""
A14.1′/A14.2′ — `verity agent-check`: run, localise, confirm, report.

Tested without a browser or a model: a fake agent produces a scripted episode,
and the check localises the failure to a step and a control, pins it to a WCAG
criterion, and reports it `needs-review` unless a confirmer upgrades it. The
report builders (AuditReport → SARIF/JSON, HTML trace) are exercised on the
result. The safety rule is the headline: an unconfirmed agent failure never
becomes a confirmed site defect.
"""

from eval.agentbench.env import Episode, Step
from eval.agentbench.agents.tree_agent import TreeAgentResult
from verity.agent_check.check import agent_check, default_confirm, localize_failure
from verity.agent_check.report import build_audit_report, write_reports
from verity.models.schemas import Confidence, Provenance


# --- fakes -----------------------------------------------------------------

def _result(steps, *, done=False, infeasible=False, looped=False):
    ep = Episode(task="url", seed=0, defect=None, goal="Add the first product to the cart")
    ep.steps = steps
    ep.done = done
    ep.reward = 1.0 if done else 0.0
    r = TreeAgentResult(episode=ep, provider="fake", model="fake-1", steps_used=len(steps))
    r.infeasible = infeasible
    r.looped = looped
    return r


class FakeAgent:
    def __init__(self, result):
        self._result = result

    def run(self, env, task, seed=0, defect=None, attack=None):
        return self._result


# --- localisation -----------------------------------------------------------

def test_success_has_no_finding():
    agent = FakeAgent(_result([Step(observation='[1] button "Buy"', action="click bid=1", ok=True)], done=True))
    res = agent_check("http://x", "buy", agent=agent, env=object())
    assert res.succeeded and res.verdict == "passed" and res.findings == []


def test_localizes_unnamed_control_to_4_1_2():
    # The agent gave up facing a button with no accessible name.
    steps = [Step(observation='[1] button\n[2] textbox "Email"', action="report_infeasible", ok=True)]
    res = agent_check("http://x", "submit the form", agent=FakeAgent(_result(steps, infeasible=True)), env=object())
    assert res.succeeded is False and res.verdict == "infeasible"
    loc = res.localization
    assert loc.sc_id == "4.1.2" and loc.selector == '[data-vbid="1"]'
    # Exactly one finding, and it is needs-review (not confirmed).
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.provenance == Provenance.NEEDS_REVIEW and f.outcome == "cantTell"
    assert f.sc.id == "4.1.2" and f.agent == "agent-check"


def test_localizes_div_button_roleless_clickable():
    steps = [Step(observation='[5] generic "Go" (clickable)', action="<loop-guard: stuck>", ok=False)]
    loc = localize_failure(_result(steps, looped=True).episode, _result(steps, looped=True))
    assert loc.sc_id == "4.1.2" and "div-button" in loc.reason and loc.selector == '[data-vbid="5"]'


def test_confirmer_upgrades_to_authoritative():
    def confirm(loc):
        return (Provenance.AUTHORITATIVE,
                Confidence(score=1.0, method="deterministic", model=None, escape_used=False), "fail")

    steps = [Step(observation='[1] button', action="report_infeasible", ok=True)]
    res = agent_check("http://x", "t", agent=FakeAgent(_result(steps, infeasible=True)),
                      env=object(), confirm_fn=confirm)
    f = res.findings[0]
    assert f.provenance == Provenance.AUTHORITATIVE and f.outcome == "fail"


def test_default_confirm_never_confirms():
    from verity.agent_check.check import Localization

    prov, conf, outcome = default_confirm(Localization(step=1, sc_id="4.1.2", reason="x"))
    assert prov == Provenance.NEEDS_REVIEW and outcome == "cantTell" and conf.escape_used is True


def test_success_fn_overrides_self_report():
    # The agent thinks it is done, but the deterministic check says it failed.
    agent = FakeAgent(_result([Step(observation='[1] button "x"', action="done", ok=True)], done=True))
    res = agent_check("http://x", "t", agent=agent, env=object(), success_fn=lambda env: "failure")
    assert res.succeeded is False and res.success_source.startswith("deterministic")
    assert len(res.findings) == 1


def test_agent_that_never_acted_is_inconclusive_with_no_finding():
    # Found in the W18 demo run (31 Oct): every answer was cut off before an
    # action, yet the page's unnamed button was reported as the CONFIRMED
    # cause. An agent that never touched the page proves nothing about it.
    def confirm(loc):  # would confirm anything — must never be reached
        return (Provenance.AUTHORITATIVE,
                Confidence(score=1.0, method="deterministic", model=None, escape_used=False), "fail")

    steps = [Step(observation='[3] button\n[9] button', action="Okay, let me think…", ok=False,
                  error="unparseable action") for _ in range(3)]
    res = agent_check("http://x", "Place the order", agent=FakeAgent(_result(steps)),
                      env=object(), success_fn=lambda env: "failure", confirm_fn=confirm)
    assert res.succeeded is False and res.verdict == "inconclusive"
    assert res.findings == [] and res.localization is None


def test_one_real_action_among_parse_failures_still_localises():
    steps = [Step(observation='[3] button', action="garbled", ok=False, error="unparseable action"),
             Step(observation='[3] button', action="report_infeasible", ok=True)]
    res = agent_check("http://x", "t", agent=FakeAgent(_result(steps, infeasible=True)), env=object())
    assert res.verdict == "infeasible" and len(res.findings) == 1


# --- reports ----------------------------------------------------------------

def test_build_audit_report_wraps_findings():
    steps = [Step(observation='[1] button', action="report_infeasible", ok=True)]
    res = agent_check("http://x", "t", agent=FakeAgent(_result(steps, infeasible=True)), env=object())
    report = build_audit_report(res)
    assert report.target == "http://x" and report.standard == "WCAG2.2-AA"
    assert len(report.findings) == 1


def test_write_reports_emits_json_sarif_html(tmp_path):
    steps = [Step(observation='[1] button', action="report_infeasible", ok=True)]
    res = agent_check("http://x", "add to cart",
                      agent=FakeAgent(_result(steps, infeasible=True)), env=object())
    written = write_reports(
        res, json_path=str(tmp_path / "r.json"),
        sarif_path=str(tmp_path / "r.sarif"), html_path=str(tmp_path / "trace.html"),
    )
    assert written["json"].exists() and written["sarif"].exists() and written["html"].exists()
    # The HTML trace replays the step with the tree the agent saw.
    html = written["html"].read_text()
    assert html.startswith("<!doctype html>") and "report_infeasible" in html
    # SARIF carries the finding as a note (needs-review does not gate).
    import json
    sarif = json.loads(written["sarif"].read_text())
    results = sarif["runs"][0]["results"]
    assert results and results[0]["level"] == "note"
