"""
B10.3′ — model providers behind one interface (Track B, Week 10).

    from eval.agentbench.providers import make_provider, CostLedger, Message

    ledger = CostLedger(cap_usd=150, path=Path("runs/pilot/ledger.jsonl"))
    llm = make_provider("anthropic:claude-sonnet-5-5", ledger=ledger)
    out = llm.complete([Message(role="user", content=tree_text)], system=AGENT_PROMPT, tag="ep-0007")
    out.text, out.usage, out.cost_usd, out.timing

Spec strings: `anthropic:<model>`, `openai:<model>`, `ollama:<model>` (the
model may itself contain ':' — `ollama:qwen3:8b`).
"""

from __future__ import annotations

from eval.agentbench.providers.base import (
    BaseProvider,
    Completion,
    Message,
    ProviderError,
    Timing,
    Usage,
)
from eval.agentbench.providers.ledger import BudgetExceeded, CostLedger
from eval.agentbench.providers.pricing import PricingTable, UnpricedModel, default_pricing

PROVIDERS = ("anthropic", "openai", "ollama")


def make_provider(spec: str, **kwargs) -> BaseProvider:
    """Build a provider from `name:model`. Keyword arguments go to the provider."""
    name, sep, model = spec.partition(":")
    if not sep or not model:
        raise ValueError(f"provider spec must be 'name:model', got {spec!r}")
    if name == "anthropic":
        from eval.agentbench.providers.anthropic import AnthropicProvider
        return AnthropicProvider(model, **kwargs)
    if name == "openai":
        from eval.agentbench.providers.openai import OpenAIProvider
        return OpenAIProvider(model, **kwargs)
    if name == "ollama":
        from eval.agentbench.providers.ollama import OllamaProvider
        return OllamaProvider(model, **kwargs)
    raise ValueError(f"unknown provider {name!r}; expected one of {', '.join(PROVIDERS)}")


__all__ = [
    "BaseProvider", "BudgetExceeded", "Completion", "CostLedger", "Message", "PricingTable",
    "ProviderError", "Timing", "UnpricedModel", "Usage", "default_pricing", "make_provider",
]
