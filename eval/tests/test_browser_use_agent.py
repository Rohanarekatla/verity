"""
A13.1′ — the browser-use (DOM) agent.

Proves it drives the episode through `env.observe_dom` (not the accessibility
tree), completes a task, and — the H2 mechanism — can act on an element whose
visible text is present in the DOM even when its accessible name is gone. Shares
the tree agent's control loop, so the loop/parse/economics behaviour is covered
by the tree-agent tests; here the focus is the observation channel.
"""

from eval.agentbench.agents.browser_use_agent import BrowserUseAgent
from eval.agentbench.providers.base import Completion, Timing, Usage


class FakeDomEnv:
    """Exposes observe_dom (DOM) and observe (tree). Under 'strip_name' the tree
    hides the button's name but the DOM keeps its visible text — the browser-use
    agent sees the latter. Completes after one click."""

    def __init__(self, defect=None):
        self._defect = defect
        self._acts = 0
        self.injected = None

    def reset(self, task, seed, defect=None):
        self._defect = defect
        self._acts = 0
        return f"goal {task}"

    def observe(self):  # the tree: name lost under strip_name
        return '[1] button' if self._defect == "strip_name" else '[1] button "Submit"'

    def observe_dom(self):  # the DOM: visible text survives
        return '[1] button "Submit" {type=submit}'

    def inject_attack(self, name):
        self.injected = name

    def act(self, action):
        self._acts += 1
        return None

    def status(self):
        return (self._acts >= 1, 1.0 if self._acts >= 1 else 0.0)


class ScriptedProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.last_prompt = None

    def complete(self, messages, *, system=None, max_tokens=512, tag=None, **kw):
        self.last_prompt = messages[0].content
        return Completion(provider="fake", model="fake-1", text='{"action":"click","bid":1}',
                          usage=Usage(input_tokens=8, output_tokens=3), timing=Timing(wall_s=0.0),
                          cost_usd=0.001)


def test_browser_use_agent_uses_the_dom_observation():
    prov = ScriptedProvider()
    agent = BrowserUseAgent(prov)
    r = agent.run(FakeDomEnv(defect="strip_name"), "click-button", seed=0, defect="strip_name")
    # The prompt carried the DOM (with visible text), not the stripped tree.
    assert '[1] button "Submit" {type=submit}' in prov.last_prompt
    # It clicked and the task completed.
    assert r.episode.done and r.episode.reward == 1.0
    assert r.episode.steps[0].observation.startswith('[1] button "Submit"')


def test_browser_use_agent_injects_attack_when_asked():
    env = FakeDomEnv()
    BrowserUseAgent(ScriptedProvider()).run(env, "t", seed=0, attack="visible_banner")
    assert env.injected == "visible_banner"


def test_browser_use_result_carries_economics():
    r = BrowserUseAgent(ScriptedProvider()).run(FakeDomEnv(), "t", seed=0)
    assert r.total_tokens == 11 and r.cost_usd == 0.001
    assert r.provider == "fake"
