"""
Weeks 18–20 — community rule packs with the mandatory fixture gate and the
sandbox (S19.5/S19.6), the security pass (S20.1), and the demo page (W18).
"""

import sys
from pathlib import Path

import pytest

from eval.security_scan import scan, scan_text
from verity.plugins import RulePackError, findings_for, load_pack, load_packs, run_pack, verify_pack

REPO = Path(__file__).resolve().parents[2]


def write_pack(tmp_path, body: str, pass_html: str, fail_html: str, script: str = None):
    (tmp_path / "fixtures").mkdir(exist_ok=True)
    (tmp_path / "fixtures" / "p.html").write_text(pass_html, encoding="utf-8")
    (tmp_path / "fixtures" / "f.html").write_text(fail_html, encoding="utf-8")
    if script is not None:
        (tmp_path / "rule.py").write_text(script, encoding="utf-8")
    path = tmp_path / "x.verity-rule.yaml"
    path.write_text(body + "\nfixtures: {pass: fixtures/p.html, fail: fixtures/f.html}\n", encoding="utf-8")
    return path


DECL = 'id: imgs\nsc: "1.1.1"\ndescription: images need alt\nselect: img\nassert: {attribute_present: alt}'


def test_the_shipped_example_pack_passes_its_own_fixtures():
    packs, problems = load_packs(REPO / "rulepacks")
    assert problems == [] and [p.id for p in packs] == ["example-icon-buttons-named"]


def test_a_declarative_rule_finds_the_defect_and_names_the_element(tmp_path):
    pack = load_pack(write_pack(tmp_path, DECL, '<img alt="x" src="a">', '<img id="logo" src="a">'))
    assert verify_pack(pack) == []
    assert run_pack(pack, '<img id="logo" src="a">') == [{"selector": "#logo", "message": "images need alt"}]


def test_fixtures_are_mandatory_and_a_rule_that_checks_nothing_is_rejected(tmp_path):
    with pytest.raises(RulePackError, match="fixtures"):
        p = tmp_path / "y.verity-rule.yaml"
        p.write_text(DECL + "\n", encoding="utf-8")
        load_pack(p)
    lazy = load_pack(write_pack(tmp_path, DECL, '<img alt="x" src="a">', '<img alt="y" src="b">'))
    assert any("checks nothing" in x for x in verify_pack(lazy))


def test_a_false_alarm_on_the_pass_fixture_rejects_the_pack(tmp_path):
    noisy = load_pack(write_pack(tmp_path, DECL, '<img src="a">', '<img src="b">'))
    assert any("false alarm" in x for x in verify_pack(noisy))


def test_unknown_keys_and_bad_assertions_are_errors(tmp_path):
    with pytest.raises(RulePackError, match="unknown key"):
        load_pack(write_pack(tmp_path, DECL + "\ngates: true", "<p></p>", "<p></p>"))
    with pytest.raises(RulePackError, match="assert"):
        load_pack(write_pack(tmp_path, DECL.replace("attribute_present: alt", "is_pretty: true"), "<p></p>",
                             "<p></p>"))


PY_RULE = 'id: py\nsc: "4.1.2"\ndescription: d\nscript: rule.py'


def test_a_python_rule_runs_sandboxed(tmp_path):
    script = ("def check(html):\n"
              "    return [{'selector': '#x', 'message': 'found'}] if 'bad' in html else []\n")
    pack = load_pack(write_pack(tmp_path, PY_RULE, "<p>good</p>", "<p>bad</p>", script))
    assert verify_pack(pack) == []


@pytest.mark.parametrize("body, why", [
    ("import socket\n    socket.create_connection(('example.com', 80))", "network"),
    ("open('C:/verity-escape.txt' if __import__('os').name == 'nt' else '/tmp/../verity-escape.txt', 'w')",
     "temp directory"),
])
def test_the_sandbox_refuses_network_and_writes_outside_temp(tmp_path, body, why):
    script = f"def check(html):\n    {body}\n    return []\n"
    pack = load_pack(write_pack(tmp_path, PY_RULE, "<p></p>", "<p></p>", script))
    with pytest.raises(RulePackError, match="rule failed"):
        run_pack(pack, "<p></p>")


def test_a_hanging_rule_times_out(tmp_path):
    from verity import plugins

    pack = load_pack(write_pack(tmp_path, PY_RULE, "<p></p>", "<p></p>",
                                "def check(html):\n    while True: pass\n"))
    with pytest.raises(RulePackError, match="timed out"):
        plugins.run_python(pack, "<p></p>", timeout=2)


def test_community_findings_never_gate(tmp_path):
    pack = load_pack(write_pack(tmp_path, DECL, '<img alt="x" src="a">', '<img id="logo" src="a">'))
    [f] = findings_for([pack], '<img id="logo" src="a">', page_state_hash="h")
    assert f.provenance.value == "needs review" and f.outcome == "cantTell"
    assert f.rule_id == "rulepack/imgs" and f.sc.id == "1.1.1"


# --- S20.1 security pass -----------------------------------------------------------

def test_secrets_are_found_and_never_printed():
    key = "sk-ant-" + "a1B2c3D4" * 5
    hits = scan_text(f'ANTHROPIC_API_KEY="{key}"\nnothing here', "trace.json")
    assert [(h.line, h.kind) for h in hits] == [(1, "anthropic-key")]
    assert key not in str(hits[0])


def test_placeholders_are_not_secrets():
    assert scan_text('api_key = "sk-test-placeholder-not-real-at-all"', "README.md") == []


def test_the_repository_itself_is_clean():
    hits, _ = scan([REPO / "verity", REPO / "eval", REPO / "docs", REPO / "data", REPO / "action"])
    assert hits == [], "\n".join(map(str, hits))


# --- W18 demo page ------------------------------------------------------------------

def test_the_demo_page_has_exactly_the_one_defect_the_story_needs():
    from bs4 import BeautifulSoup

    html = (REPO / "data" / "demo" / "checkout" / "index.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    btn = soup.select_one("#place-order")
    assert btn.get("aria-label") is None and btn.span["aria-hidden"] == "true"
    assert soup.select_one('label[for="email"]') and soup.select_one("#email")
