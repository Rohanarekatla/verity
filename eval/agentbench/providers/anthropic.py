"""
Anthropic Messages API provider (B10.3′).

API version **2026-10-21** (checked 2026-10-24 against the migration guide,
platform.claude.com/docs/en/api/migration-2026-10-21). Two consequences for
the benchmark:

- **No sampling parameters.** 2026-10-21 rejects `temperature`, `top_p` and
  `top_k` with a 400, even at their defaults, so none is sent; every call
  samples at the model's default. `seed` is not an API parameter either.
  Claude runs are therefore nondeterministic by construction — which is why
  the design is repeated trials with paired comparisons, never single runs.
- The key is sent as `Authorization: Bearer` (the API accepts it in either
  header; this is what the 2.x SDKs send).

**Prompt caching.** Two cache points, which together cover how an agent
episode is shaped:

1. an explicit breakpoint on the system prompt — the long, identical
   instructions + action schema every episode shares, so the second episode
   of a run reads them from cache;
2. top-level automatic caching (`cache_control` on the request), which moves
   the breakpoint to the end of the conversation each turn, so turn N+1 reads
   turns 1..N from cache.

Below the model's minimum cacheable length nothing is cached and no error is
returned; `Usage.cache_read_tokens == cache_write_tokens == 0` says so.
"""

from __future__ import annotations

import os
from typing import Optional

from eval.agentbench.providers.base import BaseProvider, Completion, Message, ProviderError, Timing, Usage

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2026-10-21"
_EPHEMERAL = {"type": "ephemeral"}


class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self, model: str, *, api_key: Optional[str] = None, base_url: str = API_URL, **kw):
        super().__init__(model, **kw)
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ProviderError(self.name, "no API key: set ANTHROPIC_API_KEY")
        self.base_url = base_url

    def _request(self, messages: list[Message], *, system, max_tokens, cache, seed, cache_key):
        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": m.role, "content": [{"type": "text", "text": m.content}]} for m in messages],
        }
        if system:
            block = {"type": "text", "text": system}
            if cache:
                block["cache_control"] = dict(_EPHEMERAL)
            body["system"] = [block]
        if cache:
            body["cache_control"] = dict(_EPHEMERAL)
        headers = {
            "content-type": "application/json",
            "anthropic-version": API_VERSION,
            "authorization": f"Bearer {self._api_key}",
        }
        return self.base_url, headers, body

    def _parse(self, body: dict, wall_s: float) -> Completion:
        text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
        u = body.get("usage") or {}
        return Completion(
            provider=self.name,
            model=body.get("model") or self.model,
            text=text,
            stop_reason=body.get("stop_reason"),
            usage=Usage(
                input_tokens=int(u.get("input_tokens") or 0),
                output_tokens=int(u.get("output_tokens") or 0),
                cache_read_tokens=int(u.get("cache_read_input_tokens") or 0),
                cache_write_tokens=int(u.get("cache_creation_input_tokens") or 0),
            ),
            timing=Timing(wall_s=wall_s),
            request_id=body.get("id"),
        )
