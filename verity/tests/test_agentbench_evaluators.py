"""
B11.1′ (Track B, Week 11) — deterministic task-success evaluators.

Pure: observations are built by hand and the API/DB side channels are fakes
(plus one real read-only SQLite file), so no browser and no server.
"""

import sqlite3

import pytest

from eval.agentbench.evaluators import (
    COLLECT_JS,
    ElementState,
    Observation,
    evaluate,
    observation_from_page,
    parse_spec,
    requirements,
    tasks_missing_evaluators,
    verify_evaluator,
)

CART = {"all": [
    {"url": {"matches": r"/cart$"}},
    {"element": {"selector": "#cart-count", "text_equals": "1"}},
]}


def obs(url="http://localhost:3000/cart", count="1", **kw) -> Observation:
    return Observation(url=url, elements={"#cart-count": [ElementState(text=count)]}, **kw)


# --- the spec ---------------------------------------------------------------------

def test_a_typo_in_a_check_is_an_error_not_a_silent_pass():
    with pytest.raises(Exception):
        parse_spec({"element": {"selector": "#x", "text_equal": "1"}})


def test_there_is_no_llm_judged_check():
    with pytest.raises(ValueError, match="never judged by a model"):
        parse_spec({"llm_judge": {"question": "did it work?"}})


def test_a_check_with_no_condition_is_rejected():
    with pytest.raises(Exception, match="no condition"):
        parse_spec({"element": {"selector": "#x"}})


@pytest.mark.parametrize("query", ["DELETE FROM orders", "SELECT 1; DROP TABLE orders", "UPDATE t SET a=1"])
def test_sqlite_checks_must_be_a_single_read_only_select(query):
    with pytest.raises(Exception, match="read-only"):
        parse_spec({"sqlite": {"db": "x.db", "query": query, "equals": 1}})


def test_requirements_list_what_the_page_must_be_asked_for():
    spec = {"all": [{"element": {"selector": "#a", "attribute": {"name": "aria-checked", "equals": "true"}}},
                    {"storage": {"key": "cart", "absent": True}}]}
    assert requirements(spec) == {"selectors": {"#a": ["aria-checked"]}, "storageKeys": ["cart"]}


# --- outcomes ---------------------------------------------------------------------

def test_solved_state_is_success():
    assert evaluate(CART, obs()).outcome == "success"


def test_one_definite_miss_fails_the_task():
    r = evaluate(CART, obs(count="0"))
    assert r.outcome == "failure" and "#cart-count" in r.detail


def test_a_definite_miss_stands_even_when_another_check_cannot_run():
    spec = {"all": [{"element": {"selector": "#cart-count", "text_equals": "1"}},
                    {"http": {"url": "http://localhost:3000/api/cart", "json_path": "count", "equals": 1}}]}

    def down(url):
        raise ConnectionError

    assert evaluate(spec, obs(count="0"), http_get=down).outcome == "failure"


def test_a_check_that_cannot_run_is_indeterminate_never_failure():
    r = evaluate(CART, Observation(error="TargetClosedError: page closed"))
    assert r.outcome == "indeterminate"


def test_any_succeeds_on_one_route():
    spec = {"any": [{"url": {"path_equals": "/done"}}, {"element": {"selector": "#cart-count", "exists": True}}]}
    assert evaluate(spec, obs(url="http://localhost/elsewhere")).outcome == "success"


def test_element_conditions_any_vs_all():
    o = Observation(url="u", elements={".item": [ElementState(text="A"), ElementState(text="B")]})
    assert evaluate({"element": {"selector": ".item", "text_equals": "A"}}, o).outcome == "success"
    assert evaluate({"element": {"selector": ".item", "text_equals": "A", "which": "all"}}, o).outcome == "failure"
    assert evaluate({"element": {"selector": ".item", "count": 2}}, o).outcome == "success"


def test_a_selector_the_page_rejected_is_indeterminate():
    o = Observation(url="http://localhost:3000/cart", elements={"#cart-count": None})
    assert evaluate(CART, o).outcome == "indeterminate"


def test_storage_with_a_json_path():
    o = Observation(url="u", storage={"cart": '{"items": [{"sku": "A1"}]}'})
    assert evaluate({"storage": {"key": "cart", "json_path": "items.0.sku", "equals": "A1"}}, o).outcome == "success"
    assert evaluate({"storage": {"key": "cart", "json_path": "items.1.sku", "equals": "A1"}}, o).outcome == "failure"


def test_http_checks_only_query_the_app_under_test():
    spec = {"http": {"url": "https://example.com/api", "json_path": "ok", "equals": True}}
    assert evaluate(spec, obs(), http_get=lambda u: {"ok": True}).outcome == "indeterminate"
    local = {"http": {"url": "http://localhost:3000/api/articles", "json_path": "articlesCount", "equals": 1}}
    assert evaluate(local, obs(), http_get=lambda u: {"articlesCount": 1}).outcome == "success"


def test_sqlite_check_against_a_real_read_only_database(tmp_path):
    db = tmp_path / "app.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE orders (user TEXT)")
    conn.execute("INSERT INTO orders VALUES ('bot')")
    conn.commit()
    conn.close()
    spec = {"sqlite": {"db": str(db), "query": "SELECT count(*) FROM orders WHERE user='bot'", "equals": 1}}
    assert evaluate(spec, obs()).outcome == "success"
    missing = {"sqlite": {"db": str(tmp_path / "nope.db"), "query": "SELECT 1", "equals": 1}}
    assert evaluate(missing, obs()).outcome == "indeterminate"


def test_miniwob_tasks_use_the_environment_reward():
    spec = {"env_reward": {"min": 1.0}}
    assert evaluate(spec, Observation(env_reward=1.0)).outcome == "success"
    assert evaluate(spec, Observation(env_reward=0.0)).outcome == "failure"
    assert evaluate(spec, Observation()).outcome == "indeterminate"


# --- the evaluator gate -----------------------------------------------------------

def test_an_evaluator_must_fail_the_start_state_and_pass_the_solved_one():
    assert verify_evaluator(CART, obs(count="0"), obs()) == []
    lazy = {"element": {"selector": "#cart-count", "exists": True}}  # true before the agent does anything
    problems = verify_evaluator(lazy, obs(count="0"), obs())
    assert problems and "start state" in problems[0]


def test_tasks_missing_evaluators_names_them():
    tasks = [{"id": "t1", "success": CART}, {"id": "t2"}, {"id": "t3", "success": {"judge": {}}}]
    missing = tasks_missing_evaluators(tasks)
    assert [m.split(":")[0] for m in missing] == ["t2", "t3"]


# --- reading the page ---------------------------------------------------------------

class FakePage:
    url = "http://localhost:3000/cart"

    def __init__(self, raw=None, boom=False):
        self.raw, self.boom, self.args = raw, boom, None

    def evaluate(self, js, args):
        if self.boom:
            raise RuntimeError("Target page, context or browser has been closed")
        assert js is COLLECT_JS
        self.args = args
        return self.raw


def test_observation_is_read_in_one_call_and_a_dead_page_is_not_a_crash():
    page = FakePage({"elements": {"#cart-count": [{"text": "1", "value": None, "visible": True, "attributes": {}}]},
                     "storage": {}})
    o = observation_from_page(page, CART)
    assert page.args == {"selectors": {"#cart-count": []}, "storageKeys": []}
    assert evaluate(CART, o).outcome == "success"
    dead = observation_from_page(FakePage(boom=True), CART)
    assert dead.error and evaluate(CART, dead).outcome == "indeterminate"
