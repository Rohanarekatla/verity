"""
eval/agentbench — the Agent Accessibility Benchmark (plan v2, ADR-0005).

Layout (execution-plan.md, "Architecture additions"):

    providers/   Track B, B10.3′/B10.4 — Anthropic · OpenAI · Ollama behind one
                 interface, with token, cost and timing accounting
    agents/      Track A, A10.4 — tree_agent (AXTree-only), later browser_use
                 and the screen-reader agent (B13.1′)
    evaluators   Track B, B11.1′ — deterministic task-success checks
    analysis     Track B, B11.3′ — the pre-registered statistics
"""
