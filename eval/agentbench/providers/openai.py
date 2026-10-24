"""
OpenAI Chat Completions provider (B10.3′) — also any OpenAI-compatible server
(vLLM, LM Studio) via `base_url`.

- `max_completion_tokens`, not the deprecated `max_tokens`.
- No `temperature` by default: reasoning models reject non-default values,
  and leaving it out keeps every provider on its default sampling, which is
  what the benchmark compares. `seed` is sent when given (best-effort
  determinism on OpenAI's side) and recorded either way.
- **Prompt caching is automatic** (prompts of 1,024+ tokens). There is nothing
  to switch on; we only read what was cached. `cache_key`, when given, is sent
  as `prompt_cache_key` so episodes of the same task route to the same cache.

Usage conversion: OpenAI's `prompt_tokens` INCLUDES cached tokens. We split
it the Anthropic way — `input_tokens` is what was neither read from nor
written to cache — so `Usage` means the same thing for every provider.
"""

from __future__ import annotations

import os
from typing import Optional

from eval.agentbench.providers.base import BaseProvider, Completion, Message, ProviderError, Timing, Usage

API_BASE = "https://api.openai.com/v1"


class OpenAIProvider(BaseProvider):
    name = "openai"

    def __init__(self, model: str, *, api_key: Optional[str] = None, base_url: str = API_BASE, **kw):
        super().__init__(model, **kw)
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise ProviderError(self.name, "no API key: set OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")

    def _request(self, messages: list[Message], *, system, max_tokens, cache, seed, cache_key):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": m.role, "content": m.content} for m in messages]
        body: dict = {"model": self.model, "messages": msgs, "max_completion_tokens": max_tokens}
        if seed is not None:
            body["seed"] = seed
        if cache and cache_key:
            body["prompt_cache_key"] = cache_key
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._api_key}"}
        return f"{self.base_url}/chat/completions", headers, body

    def _parse(self, body: dict, wall_s: float) -> Completion:
        choices = body.get("choices") or [{}]
        msg = choices[0].get("message") or {}
        u = body.get("usage") or {}
        details = u.get("prompt_tokens_details") or {}
        prompt = int(u.get("prompt_tokens") or 0)
        cached = int(details.get("cached_tokens") or 0)
        written = int(details.get("cache_write_tokens") or u.get("cache_write_tokens") or 0)
        return Completion(
            provider=self.name,
            model=body.get("model") or self.model,
            text=msg.get("content") or "",
            stop_reason=choices[0].get("finish_reason"),
            usage=Usage(
                input_tokens=max(0, prompt - cached - written),
                output_tokens=int(u.get("completion_tokens") or 0),
                cache_read_tokens=cached,
                cache_write_tokens=written,
            ),
            timing=Timing(wall_s=wall_s),
            request_id=body.get("id"),
        )
