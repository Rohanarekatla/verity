"""
B11.1′ — deterministic task-success evaluators (Track B, Week 11).

Did the agent complete the task? The benchmark's primary metric is task
success, so this is the one judgment in the whole study that must not be a
judgment: **no LLM decides success.** A task declares, in its YAML, what the
world looks like when it is done — the URL, an element's text or value, a
localStorage entry, the app's own API, its database, or BrowserGym's reward
for MiniWoB++ — and this module checks exactly that.

    success:
      all:
        - url: {matches: "/cart$"}
        - element: {selector: "#cart-count", text_equals: "1"}
        - sqlite: {db: "apps/shop/data.db", query: "SELECT count(*) FROM orders", equals: 1}

Three outcomes, same doctrine as the keyboard wedge (ADR-0004):

- `success`       every required condition holds;
- `failure`       a condition was checked and does not hold — evidence stands
                  alone, so one definite miss fails an `all:` even if another
                  check could not run;
- `indeterminate` a check could not run (page gone, API down, DB missing,
                  bad selector). Never counted as the agent failing: the
                  pre-registration excludes these episodes, and says so.

Structure: the page is read ONCE, at episode end, into an `Observation` (one
`page.evaluate` with `COLLECT_JS`, sync or async Playwright alike); the
checks are then pure functions of it. The API and DB checks query the app
directly, through injectable fetchers, so tests need no browser or server.

A9.4's lesson applies here too: an evaluator that cannot fail checks nothing.
`verify_evaluator` requires every task's evaluator to report `failure` on the
task's start state and `success` on its solved state.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Callable, Literal, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator

Outcome = Literal["success", "failure", "indeterminate"]


# --- the spec (YAML), validated strictly ------------------------------------------
#
# extra="forbid" everywhere: a typo'd `text_equal:` that silently checked
# nothing would make every episode a success.

class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UrlCheck(_Strict):
    equals: Optional[str] = None
    matches: Optional[str] = None      # regex, searched in the full URL
    path_equals: Optional[str] = None

    @model_validator(mode="after")
    def _one(self):
        if sum(x is not None for x in (self.equals, self.matches, self.path_equals)) != 1:
            raise ValueError("url: give exactly one of equals / matches / path_equals")
        return self


class AttributeCondition(_Strict):
    name: str
    equals: Optional[str] = None
    absent: bool = False


class ElementCheck(_Strict):
    selector: str
    which: Literal["any", "all"] = "any"
    exists: Optional[bool] = None
    count: Optional[int] = Field(default=None, ge=0)
    text_equals: Optional[str] = None
    text_contains: Optional[str] = None
    value_equals: Optional[str] = None
    visible: Optional[bool] = None
    attribute: Optional[AttributeCondition] = None

    @model_validator(mode="after")
    def _something(self):
        conds = (self.exists, self.count, self.text_equals, self.text_contains, self.value_equals,
                 self.visible, self.attribute)
        if all(c is None for c in conds):
            raise ValueError(f"element {self.selector!r}: no condition given")
        return self


class StorageCheck(_Strict):
    key: str
    equals: Optional[Any] = None
    json_path: Optional[str] = None    # dotted, integer indexes: "items.0.sku"
    absent: bool = False


class HttpCheck(_Strict):
    url: str
    json_path: Optional[str] = None
    equals: Any = None


class SqliteCheck(_Strict):
    db: str
    query: str
    equals: Any = None

    @model_validator(mode="after")
    def _read_only(self):
        if not re.match(r"^\s*(select|with)\b", self.query, re.I) or ";" in self.query.strip().rstrip(";"):
            raise ValueError("sqlite: a single read-only SELECT is required")
        return self


class EnvRewardCheck(_Strict):
    min: float = 1.0


_KINDS = {"url": UrlCheck, "element": ElementCheck, "storage": StorageCheck, "http": HttpCheck,
          "sqlite": SqliteCheck, "env_reward": EnvRewardCheck}

Spec = Union[dict, list]


def parse_spec(spec: Spec) -> tuple:
    """
    Validate a `success:` block into a tree of ("all"|"any", [children]) and
    (kind, Check) leaves. Raises on anything unknown — including any attempt
    to declare an LLM-judged check, which is not a kind that exists.
    """
    if isinstance(spec, list):
        return ("all", [parse_spec(s) for s in spec])
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError(f"each success entry must be a one-key mapping, got {spec!r}")
    (key, value), = spec.items()
    if key in ("all", "any"):
        if not isinstance(value, list) or not value:
            raise ValueError(f"{key}: must be a non-empty list")
        return (key, [parse_spec(v) for v in value])
    if key not in _KINDS:
        raise ValueError(f"unknown success check {key!r}; known: {', '.join(sorted(_KINDS))} "
                         "(success is never judged by a model)")
    return (key, _KINDS[key].model_validate(value or {}))


# --- the observation ---------------------------------------------------------------

class ElementState(BaseModel):
    text: str = ""
    value: Optional[str] = None
    visible: bool = True
    attributes: dict[str, Optional[str]] = {}


class Observation(BaseModel):
    """Everything the page-side checks need, read once at episode end."""
    url: Optional[str] = None
    # selector -> matched elements; a selector the page rejected maps to None
    elements: dict[str, Optional[list[ElementState]]] = {}
    storage: dict[str, Optional[str]] = {}
    env_reward: Optional[float] = None
    error: Optional[str] = None    # the page could not be read at all


def requirements(spec: Spec) -> dict:
    """What `COLLECT_JS` must read for this spec: selectors (+ attributes) and storage keys."""
    tree = parse_spec(spec)
    selectors: dict[str, set[str]] = {}
    keys: set[str] = set()

    def walk(node):
        kind, val = node
        if kind in ("all", "any"):
            for child in val:
                walk(child)
        elif kind == "element":
            attrs = selectors.setdefault(val.selector, set())
            if val.attribute:
                attrs.add(val.attribute.name)
        elif kind == "storage":
            keys.add(val.key)

    walk(tree)
    return {"selectors": {s: sorted(a) for s, a in selectors.items()}, "storageKeys": sorted(keys)}


# Runs in the page. One round trip, no side effects.
COLLECT_JS = """
(req) => {
  const out = { elements: {}, storage: {} };
  for (const [sel, attrs] of Object.entries(req.selectors)) {
    try {
      out.elements[sel] = Array.from(document.querySelectorAll(sel)).map((el) => {
        const a = {};
        for (const n of attrs) a[n] = el.getAttribute(n);
        const style = getComputedStyle(el);
        return {
          text: (el.innerText ?? el.textContent ?? "").replace(/\\s+/g, " ").trim(),
          value: "value" in el ? String(el.value) : null,
          visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                   && style.visibility !== "hidden",
          attributes: a,
        };
      });
    } catch (e) { out.elements[sel] = null; }
  }
  for (const k of req.storageKeys) {
    try { out.storage[k] = window.localStorage.getItem(k); } catch (e) { out.storage[k] = null; }
  }
  return out;
}
"""


def observation_from_page(page, spec: Spec, *, env_reward: Optional[float] = None) -> Observation:
    """Read a sync Playwright page (BrowserGym's) into an Observation. Never raises."""
    try:
        raw = page.evaluate(COLLECT_JS, requirements(spec))
        return Observation(url=page.url, env_reward=env_reward, **raw)
    except Exception as exc:  # the page is gone, crashed, navigated mid-read…
        return Observation(env_reward=env_reward, error=f"{exc.__class__.__name__}: {exc}"[:300])


async def observation_from_page_async(page, spec: Spec, *, env_reward: Optional[float] = None) -> Observation:
    """The same for an async Playwright page."""
    try:
        raw = await page.evaluate(COLLECT_JS, requirements(spec))
        return Observation(url=page.url, env_reward=env_reward, **raw)
    except Exception as exc:
        return Observation(env_reward=env_reward, error=f"{exc.__class__.__name__}: {exc}"[:300])


# --- side channels: the app's API and database ---------------------------------------

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def default_http_get(url: str, timeout: float = 10.0) -> Any:
    import urllib.request

    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — host checked by caller
        return json.loads(resp.read().decode("utf-8"))


def default_sql(db: str, query: str) -> list[tuple]:
    path = Path(db)
    if not path.exists():
        raise FileNotFoundError(db)
    # Read-only at the driver level too, not just by the SELECT check.
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


# --- evaluation ------------------------------------------------------------------------

class CheckResult(BaseModel):
    kind: str
    outcome: Outcome
    detail: str


class EvaluationResult(BaseModel):
    task_id: Optional[str] = None
    outcome: Outcome
    detail: str
    checks: list[CheckResult] = []


def _json_path(value: Any, path: Optional[str]) -> Any:
    if not path:
        return value
    for part in path.split("."):
        if isinstance(value, list) and part.lstrip("-").isdigit():
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(part)
    return value


class _Ctx:
    def __init__(self, obs: Observation, http_get, sql, allowed_hosts):
        self.obs, self.http_get, self.sql, self.allowed_hosts = obs, http_get, sql, allowed_hosts


def _r(kind: str, ok: Optional[bool], detail: str) -> CheckResult:
    return CheckResult(kind=kind, outcome="indeterminate" if ok is None else ("success" if ok else "failure"),
                       detail=detail)


def _check_url(c: UrlCheck, ctx: _Ctx) -> CheckResult:
    url = ctx.obs.url
    if url is None:
        return _r("url", None, ctx.obs.error or "the page URL could not be read")
    if c.equals is not None:
        return _r("url", url == c.equals, f"url {url!r} {'==' if url == c.equals else '!='} {c.equals!r}")
    if c.path_equals is not None:
        path = urlparse(url).path
        return _r("url", path == c.path_equals, f"path {path!r} vs {c.path_equals!r}")
    try:
        hit = re.search(c.matches, url) is not None
    except re.error as exc:
        return _r("url", None, f"bad regex {c.matches!r}: {exc}")
    return _r("url", hit, f"url {url!r} {'matches' if hit else 'does not match'} /{c.matches}/")


def _element_ok(c: ElementCheck, e: ElementState) -> bool:
    if c.text_equals is not None and e.text != c.text_equals:
        return False
    if c.text_contains is not None and c.text_contains not in e.text:
        return False
    if c.value_equals is not None and e.value != c.value_equals:
        return False
    if c.visible is not None and e.visible != c.visible:
        return False
    if c.attribute is not None:
        v = e.attributes.get(c.attribute.name)
        if c.attribute.absent and v is not None:
            return False
        if c.attribute.equals is not None and v != c.attribute.equals:
            return False
    return True


def _check_element(c: ElementCheck, ctx: _Ctx) -> CheckResult:
    if ctx.obs.error:
        return _r("element", None, ctx.obs.error)
    if c.selector not in ctx.obs.elements:
        return _r("element", None, f"{c.selector!r} was not collected")
    found = ctx.obs.elements[c.selector]
    if found is None:
        return _r("element", None, f"the page rejected selector {c.selector!r}")
    n = len(found)
    if c.exists is not None and (n > 0) != c.exists:
        return _r("element", False, f"{c.selector!r}: {n} match(es), expected exists={c.exists}")
    if c.count is not None and n != c.count:
        return _r("element", False, f"{c.selector!r}: {n} match(es), expected {c.count}")
    per_element = any(x is not None for x in (c.text_equals, c.text_contains, c.value_equals, c.visible,
                                              c.attribute))
    if not per_element:
        return _r("element", True, f"{c.selector!r}: {n} match(es)")
    if n == 0:
        return _r("element", False, f"{c.selector!r}: no element to check")
    oks = [_element_ok(c, e) for e in found]
    ok = all(oks) if c.which == "all" else any(oks)
    sample = found[0].text[:60]
    return _r("element", ok, f"{c.selector!r}: {sum(oks)}/{n} satisfy the condition (first text {sample!r})")


def _check_storage(c: StorageCheck, ctx: _Ctx) -> CheckResult:
    if ctx.obs.error:
        return _r("storage", None, ctx.obs.error)
    if c.key not in ctx.obs.storage:
        return _r("storage", None, f"localStorage[{c.key!r}] was not collected")
    raw = ctx.obs.storage[c.key]
    if c.absent:
        return _r("storage", raw is None, f"localStorage[{c.key!r}] is {'absent' if raw is None else 'present'}")
    if raw is None:
        return _r("storage", False, f"localStorage[{c.key!r}] is absent")
    try:
        value = _json_path(json.loads(raw), c.json_path) if c.json_path else raw
    except (ValueError, KeyError, IndexError, TypeError):
        return _r("storage", False, f"localStorage[{c.key!r}] has no {c.json_path!r}")
    return _r("storage", value == c.equals, f"localStorage[{c.key!r}]{'.' + c.json_path if c.json_path else ''} "
                                            f"= {value!r}, expected {c.equals!r}")


def _check_http(c: HttpCheck, ctx: _Ctx) -> CheckResult:
    host = urlparse(c.url).hostname or ""
    if host not in ctx.allowed_hosts and not host.endswith(".localhost"):
        return _r("http", None, f"{host!r} is not an allowed host; evaluators only query the app under test")
    try:
        body = ctx.http_get(c.url)
    except Exception as exc:
        return _r("http", None, f"GET {c.url} failed: {exc.__class__.__name__}")
    try:
        value = _json_path(body, c.json_path)
    except (KeyError, IndexError, TypeError):
        return _r("http", False, f"GET {c.url}: no {c.json_path!r} in the response")
    return _r("http", value == c.equals, f"GET {c.url} {c.json_path or ''} = {value!r}, expected {c.equals!r}")


def _check_sqlite(c: SqliteCheck, ctx: _Ctx) -> CheckResult:
    try:
        rows = ctx.sql(c.db, c.query)
    except Exception as exc:
        return _r("sqlite", None, f"query failed: {exc.__class__.__name__}: {exc}"[:200])
    value = rows[0][0] if rows and rows[0] else None
    return _r("sqlite", value == c.equals, f"{c.query.strip()[:60]!r} -> {value!r}, expected {c.equals!r}")


def _check_env_reward(c: EnvRewardCheck, ctx: _Ctx) -> CheckResult:
    r = ctx.obs.env_reward
    if r is None:
        return _r("env_reward", None, "no environment reward was recorded")
    return _r("env_reward", r >= c.min, f"reward {r} vs min {c.min}")


_CHECKERS: dict[str, Callable[[Any, _Ctx], CheckResult]] = {
    "url": _check_url, "element": _check_element, "storage": _check_storage,
    "http": _check_http, "sqlite": _check_sqlite, "env_reward": _check_env_reward,
}


def _combine(op: str, outcomes: list[Outcome]) -> Outcome:
    if op == "all":
        if "failure" in outcomes:
            return "failure"          # a definite miss stands alone
        return "indeterminate" if "indeterminate" in outcomes else "success"
    if "success" in outcomes:
        return "success"
    return "indeterminate" if "indeterminate" in outcomes else "failure"


def evaluate(
    spec: Spec,
    observation: Observation,
    *,
    task_id: Optional[str] = None,
    http_get: Callable[[str], Any] = default_http_get,
    sql: Callable[[str, str], list] = default_sql,
    allowed_hosts: frozenset = frozenset(_LOCAL_HOSTS),
) -> EvaluationResult:
    """Decide success for one episode. Deterministic; never raises on page/app state."""
    ctx = _Ctx(observation, http_get, sql, set(allowed_hosts))
    checks: list[CheckResult] = []

    def run(node) -> Outcome:
        kind, val = node
        if kind in ("all", "any"):
            return _combine(kind, [run(child) for child in val])
        result = _CHECKERS[kind](val, ctx)
        checks.append(result)
        return result.outcome

    outcome = run(parse_spec(spec))
    failed = [c.detail for c in checks if c.outcome == "failure"]
    unknown = [c.detail for c in checks if c.outcome == "indeterminate"]
    detail = ("; ".join(failed) if outcome == "failure" else
              "; ".join(unknown) if outcome == "indeterminate" else f"{len(checks)} check(s) hold")
    return EvaluationResult(task_id=task_id, outcome=outcome, detail=detail, checks=checks)


# --- the evaluator gate (the A9.4 rule, applied to tasks) ------------------------------

def verify_evaluator(spec: Spec, start: Observation, solved: Observation, **kw) -> list[str]:
    """
    An evaluator that cannot fail checks nothing; one that cannot pass is
    broken. Returns problems (empty = the evaluator is usable).
    """
    problems: list[str] = []
    try:
        parse_spec(spec)
    except Exception as exc:
        return [f"invalid success spec: {exc}"]
    at_start = evaluate(spec, start, **kw)
    if at_start.outcome != "failure":
        problems.append(f"start state evaluates to {at_start.outcome}, not failure — the evaluator cannot "
                        f"tell an untouched page from a solved one ({at_start.detail})")
    at_end = evaluate(spec, solved, **kw)
    if at_end.outcome != "success":
        problems.append(f"solved state evaluates to {at_end.outcome}, not success ({at_end.detail})")
    return problems


def tasks_missing_evaluators(tasks: list[dict]) -> list[str]:
    """Week 11 gate helper: task ids with no valid deterministic `success:` block."""
    missing = []
    for t in tasks:
        tid = str(t.get("id", "<no id>"))
        if "success" not in t:
            missing.append(f"{tid}: no success block")
            continue
        try:
            parse_spec(t["success"])
        except Exception as exc:
            missing.append(f"{tid}: {exc}")
    return missing
