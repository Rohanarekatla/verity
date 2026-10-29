"""
Agents under test in the Agent Accessibility Benchmark.

An agent is anything that, given the benchmark environment and a model
provider, drives one episode to completion and returns its trace. The first
and primary subject is the **tree-only agent** (A10.4): it sees only the
accessibility tree and acts by element id or keyboard — the interface
Playwright MCP and ChatGPT Atlas use, which is exactly why a name or role
defect that is invisible to a sighted user can still break it.
"""

from eval.agentbench.agents.tree_agent import (
    AgentAction,
    TreeAgent,
    TreeAgentResult,
    action_json_schema,
)

__all__ = ["AgentAction", "TreeAgent", "TreeAgentResult", "action_json_schema"]
