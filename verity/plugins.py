"""
S19.5 / S19.6 — community rule packs, with a mandatory fixture gate and a
sandbox for code rules.

A rule pack lets a team add project-specific checks without forking Verity
(`rulepacks/*.verity-rule.yaml`). Two kinds:

**Declarative** (preferred — no code runs at all):

    id: acme-icon-buttons-named
    sc: "4.1.2"
    description: Icon buttons must carry aria-label
    select: "button.icon"
    assert: {attribute_present: aria-label}      # or attribute_matches / text_nonempty / absent
    fixtures: {pass: fixtures/acme-pass.html, fail: fixtures/acme-fail.html}

**Python** (`script: rules/check.py` defining `check(html: str) -> list[dict]`
with `{"selector", "message"}` items) — run in a **restricted subprocess**:
isolated interpreter (`-I`), empty environment, a fresh temp directory as cwd,
networking disabled (socket creation raises), file writes refused outside the
temp directory, CPU and memory limits where the OS provides them (POSIX), and a
wall-clock timeout. Its output is validated before it can become a finding.
Honest caveat: this is a best-effort guard in-process, not a security boundary
equal to a container — on Windows the resource limits are unavailable. Treat
third-party Python rules as code you are choosing to run.

Two rules for every pack, enforced:

- **Fixtures are mandatory** (`verify_pack`): the rule must report nothing on
  its pass fixture and at least one finding on its fail fixture — the same
  A9.4 rule the APG contracts live under. A pack that fails is not loaded.
- **Community findings never gate.** They are `needs review` / `cantTell`:
  Verity has not reviewed the rule's semantics, so it annotates and never
  breaks a build.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
from bs4 import BeautifulSoup

TIMEOUT_S = 10
MAX_FINDINGS = 200


class RulePackError(ValueError):
    pass


@dataclass
class RulePack:
    id: str
    sc: str
    description: str
    path: Path
    select: Optional[str] = None
    assertion: dict = field(default_factory=dict)
    script: Optional[Path] = None
    fixtures: dict = field(default_factory=dict)


_ASSERTIONS = {"attribute_present", "attribute_matches", "text_nonempty", "absent"}


def load_pack(path: Path) -> RulePack:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    unknown = set(data) - {"id", "sc", "description", "select", "assert", "script", "fixtures"}
    if unknown:
        raise RulePackError(f"{path.name}: unknown key(s) {sorted(unknown)}")
    for key in ("id", "sc", "description", "fixtures"):
        if not data.get(key):
            raise RulePackError(f"{path.name}: `{key}` is required")
    fx = data["fixtures"]
    if not isinstance(fx, dict) or not fx.get("pass") or not fx.get("fail"):
        raise RulePackError(f"{path.name}: fixtures need both `pass` and `fail` (mandatory)")
    if bool(data.get("select")) == bool(data.get("script")):
        raise RulePackError(f"{path.name}: give exactly one of `select` (declarative) or `script` (python)")
    assertion = data.get("assert") or {}
    if data.get("select") and (len(assertion) != 1 or set(assertion) - _ASSERTIONS):
        raise RulePackError(f"{path.name}: `assert` must be one of {sorted(_ASSERTIONS)}")
    return RulePack(id=str(data["id"]), sc=str(data["sc"]), description=str(data["description"]), path=path,
                    select=data.get("select"), assertion=assertion,
                    script=(path.parent / data["script"]) if data.get("script") else None,
                    fixtures={k: path.parent / v for k, v in fx.items()})


# --- running a rule ------------------------------------------------------------------

def _css_path(el) -> str:
    if el.get("id"):
        return f"#{el['id']}"
    parts = []
    while el is not None and getattr(el, "name", None) and el.name != "[document]":
        if el.get("id"):
            parts.insert(0, f"#{el['id']}")
            break
        sibs = [s for s in el.parent.find_all(el.name, recursive=False)] if el.parent else [el]
        parts.insert(0, el.name if len(sibs) == 1 else f"{el.name}:nth-of-type({sibs.index(el) + 1})")
        el = el.parent
    return " > ".join(parts)


def run_declarative(pack: RulePack, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    (kind, arg), = pack.assertion.items()
    out = []
    for el in soup.select(pack.select):
        bad = False
        if kind == "absent":
            bad = bool(arg)
        elif kind == "attribute_present":
            bad = not (el.get(arg) or "").strip()
        elif kind == "attribute_matches":
            bad = not re.search(arg["pattern"], el.get(arg["name"]) or "")
        elif kind == "text_nonempty":
            bad = bool(arg) and not el.get_text(strip=True)
        if bad:
            out.append({"selector": _css_path(el), "message": pack.description})
    return out[:MAX_FINDINGS]


_BOOTSTRAP = textwrap.dedent('''
    import builtins, io, json, os, socket, sys, tempfile
    TMP = os.getcwd()
    def _no_net(*a, **k):
        raise PermissionError("network access is disabled for rule packs")
    socket.socket = _no_net
    socket.create_connection = _no_net
    _open = builtins.open
    def _guarded_open(file, mode="r", *a, **k):
        if any(m in mode for m in "wax+") and not os.path.abspath(str(file)).startswith(TMP):
            raise PermissionError("rule packs may only write inside their temp directory")
        return _open(file, mode, *a, **k)
    builtins.open = _guarded_open
    io.open = _guarded_open
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    except Exception:
        pass
    html = sys.stdin.read()
    ns = {"__name__": "rulepack"}
    exec(compile(SOURCE, "rulepack.py", "exec"), ns)
    result = ns["check"](html)
    sys.stdout.write(json.dumps(result))
''')


def _clean_env() -> dict:
    """An empty environment — no tokens, no proxies — except what Windows needs to start Python."""
    env = {"PYTHONIOENCODING": "utf-8"}
    for key in ("SYSTEMROOT", "SystemRoot"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run_python(pack: RulePack, html: str, *, timeout: float = TIMEOUT_S) -> list[dict]:
    source = pack.script.read_text(encoding="utf-8")
    program = f"SOURCE = {source!r}\n" + _BOOTSTRAP
    with tempfile.TemporaryDirectory(prefix="verity-rule-") as tmp:
        try:
            proc = subprocess.run([sys.executable, "-I", "-c", program], input=html, capture_output=True,
                                  text=True, timeout=timeout, cwd=tmp, env=_clean_env())
        except subprocess.TimeoutExpired:
            raise RulePackError(f"{pack.id}: timed out after {timeout}s")
    if proc.returncode != 0:
        raise RulePackError(f"{pack.id}: rule failed: {proc.stderr.strip().splitlines()[-1:] or ['error']}")
    try:
        items = json.loads(proc.stdout or "[]")
    except ValueError:
        raise RulePackError(f"{pack.id}: rule output is not JSON")
    if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("selector"), str)
                                              and isinstance(i.get("message"), str) for i in items):
        raise RulePackError(f"{pack.id}: rule output must be a list of {{selector, message}} objects")
    return items[:MAX_FINDINGS]


def run_pack(pack: RulePack, html: str) -> list[dict]:
    return run_python(pack, html) if pack.script else run_declarative(pack, html)


def verify_pack(pack: RulePack) -> list[str]:
    """The mandatory fixture gate. Empty list = the pack may be loaded."""
    problems = []
    for kind in ("pass", "fail"):
        if not pack.fixtures[kind].exists():
            problems.append(f"{pack.id}: {kind} fixture {pack.fixtures[kind]} does not exist")
    if problems:
        return problems
    try:
        on_pass = run_pack(pack, pack.fixtures["pass"].read_text(encoding="utf-8"))
        on_fail = run_pack(pack, pack.fixtures["fail"].read_text(encoding="utf-8"))
    except RulePackError as exc:
        return [str(exc)]
    if on_pass:
        problems.append(f"{pack.id}: false alarm on its own pass fixture ({on_pass[0]['selector']})")
    if not on_fail:
        problems.append(f"{pack.id}: reports nothing on its own fail fixture — the rule checks nothing")
    return problems


def load_packs(directory: Path) -> tuple[list[RulePack], list[str]]:
    """Every pack in `directory` that passes its fixture gate, plus the problems of those that do not."""
    packs, problems = [], []
    for path in sorted(Path(directory).glob("*.verity-rule.yaml")):
        try:
            pack = load_pack(path)
        except RulePackError as exc:
            problems.append(str(exc))
            continue
        issues = verify_pack(pack)
        if issues:
            problems += issues
        else:
            packs.append(pack)
    return packs, problems


def findings_for(packs: list[RulePack], html: str, *, page_state_hash: str) -> list:
    """Community findings: always needs-review / cantTell — they annotate, they never gate."""
    from verity.models.schemas import (Confidence, Evidence, Finding, Level, Modality, Provenance, Severity,
                                       SuccessCriterion)
    from verity.orchestrator.main import derive_finding_id
    from verity.standards import BY_ID

    out = []
    for pack in packs:
        try:
            items = run_pack(pack, html)
        except RulePackError:
            continue
        c = BY_ID.get(pack.sc)
        level = Level(c.level) if c else Level.A
        for item in items:
            rule_id = f"rulepack/{pack.id}"
            out.append(Finding(
                id=derive_finding_id(rule_id, item["selector"]), rule_id=rule_id,
                sc=SuccessCriterion(id=pack.sc, name=c.name if c else pack.sc, level=level,
                                    modality=Modality.PARTIAL),
                provenance=Provenance.NEEDS_REVIEW, severity=Severity.MINOR,
                confidence=Confidence(score=0.0, method="community-rulepack"), agent="rulepack",
                outcome="cantTell", message=f"[community rule {pack.id}] {item['message']}",
                evidence=Evidence(dom_selector=item["selector"]), page_state_hash=page_state_hash))
    return out
