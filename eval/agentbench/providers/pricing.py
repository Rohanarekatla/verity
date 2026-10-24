"""
B10.3′ — cost accounting: tokens -> USD, per provider and model.

Prices live in `pricing.yaml`, next to this file, with their source and an
`as_of` date. They are data, not code, because they change (Anthropic cut a
cache-read price on 7 Oct 2026) and the person sizing a run should be able to
see and fix one without reading Python.

Two refusals, both in the service of "budget is a gate, not a hope":

- a remote model with no price raises `UnpricedModel` when its provider is
  constructed, unless the caller opts out explicitly;
- a negative or missing rate in the YAML is a load error, not a zero.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

from eval.agentbench.providers.base import Usage

PRICING_PATH = Path(__file__).with_name("pricing.yaml")
_MTOK = 1_000_000


class UnpricedModel(ValueError):
    """A remote model with no entry in pricing.yaml."""


class Rates(BaseModel):
    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_write: float = Field(ge=0)
    cache_read: float = Field(ge=0)


class Price(BaseModel):
    """USD per MTok for one model, optionally with a long-context tier."""
    provider: str
    model: str
    rates: Rates
    long_context_threshold: Optional[int] = Field(default=None, gt=0)
    long_context: Optional[Rates] = None
    source: Optional[str] = None
    as_of: Optional[str] = None

    def rates_for(self, usage: Usage) -> Rates:
        if (self.long_context_threshold is not None and self.long_context is not None
                and usage.total_input > self.long_context_threshold):
            return self.long_context
        return self.rates

    def cost(self, usage: Usage) -> float:
        r = self.rates_for(usage)
        return (
            usage.input_tokens * r.input
            + usage.output_tokens * r.output
            + usage.cache_write_tokens * r.cache_write
            + usage.cache_read_tokens * r.cache_read
        ) / _MTOK


FREE = Rates(input=0, output=0, cache_write=0, cache_read=0)


class PricingTable:
    def __init__(self, prices: dict[tuple[str, str], Price], as_of: Optional[str] = None):
        self.prices = prices
        self.as_of = as_of

    def lookup(self, provider: str, model: str, *, local: bool = False) -> Optional[Price]:
        """The price for a model; local providers are free; None if unpriced."""
        if local:
            return Price(provider=provider, model=model, rates=FREE, source="local", as_of=self.as_of)
        return self.prices.get((provider, model))

    @classmethod
    def from_yaml(cls, path: Path = PRICING_PATH) -> "PricingTable":
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        as_of = str(data.get("as_of")) if data.get("as_of") else None
        prices: dict[tuple[str, str], Price] = {}
        for provider, models in (data.get("models") or {}).items():
            for model, spec in (models or {}).items():
                spec = dict(spec)
                long_rates = spec.pop("long_context", None)
                threshold = spec.pop("long_context_threshold", None)
                source = spec.pop("source", None)
                prices[(provider, model)] = Price(
                    provider=provider,
                    model=model,
                    rates=Rates.model_validate(spec),
                    long_context_threshold=threshold,
                    long_context=Rates.model_validate(long_rates) if long_rates else None,
                    source=source,
                    as_of=as_of,
                )
        return cls(prices, as_of=as_of)


@lru_cache(maxsize=1)
def default_pricing() -> PricingTable:
    return PricingTable.from_yaml()
