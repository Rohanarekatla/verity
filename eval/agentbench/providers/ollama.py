"""
Ollama provider (B10.3′, B10.4) — the local models the bulk of the benchmark
runs on (Qwen3-8B/14B per the v2 budget).

Uses the native `/api/chat` endpoint rather than Ollama's OpenAI-compatible
one, because only the native response reports **where the time went**
(nanoseconds): `load_duration`, `prompt_eval_duration`, `eval_duration`. That
is B10.4 — model-load vs inference, measured per provider rather than guessed.

- `keep_alive` keeps the model resident between episodes (default 30 min), so
  only the first call of a run pays the load; `unload()` evicts it, which is
  how `timing.py` measures a true cold load.
- Cost is zero (local). Tokens are still counted, because tokens/episode is
  half of what the W10 pilot exists to measure.
- `prompt_eval_count` counts only the prompt tokens Ollama actually
  evaluated; a prefix it reused from its KV cache is not in it, and Ollama
  does not report that prefix's size. So for local models `input_tokens` is
  "evaluated prompt tokens" and `cache_read_tokens` stays 0 — stated here so
  nobody compares the two providers' input counts as like for like.
- Sampling: Ollama's defaults unless `options` is given at construction
  (e.g. `{"temperature": 0}`); `seed` is passed through when set.
"""

from __future__ import annotations

import os
from typing import Optional

from eval.agentbench.providers.base import BaseProvider, Completion, Message, ProviderError, Timing, Usage

DEFAULT_HOST = "http://localhost:11434"
_NS = 1e9


class OllamaProvider(BaseProvider):
    name = "ollama"
    local = True

    def __init__(self, model: str, *, host: Optional[str] = None, keep_alive: str = "30m",
                 options: Optional[dict] = None, **kw):
        super().__init__(model, **kw)
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        if not self.host.startswith(("http://", "https://")):
            self.host = "http://" + self.host
        self.keep_alive = keep_alive
        self.options = dict(options or {})

    def _request(self, messages: list[Message], *, system, max_tokens, cache, seed, cache_key):
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": m.role, "content": m.content} for m in messages]
        options = dict(self.options)
        options["num_predict"] = max_tokens
        if seed is not None:
            options["seed"] = seed
        body = {"model": self.model, "messages": msgs, "stream": False,
                "keep_alive": self.keep_alive, "options": options}
        return f"{self.host}/api/chat", {"Content-Type": "application/json"}, body

    def _parse(self, body: dict, wall_s: float) -> Completion:
        def secs(key: str) -> Optional[float]:
            v = body.get(key)
            return None if v is None else float(v) / _NS

        return Completion(
            provider=self.name,
            model=body.get("model") or self.model,
            text=(body.get("message") or {}).get("content") or "",
            stop_reason=body.get("done_reason"),
            usage=Usage(
                input_tokens=int(body.get("prompt_eval_count") or 0),
                output_tokens=int(body.get("eval_count") or 0),
            ),
            timing=Timing(
                wall_s=wall_s,
                load_s=secs("load_duration"),
                prompt_eval_s=secs("prompt_eval_duration"),
                generate_s=secs("eval_duration"),
            ),
        )

    def unload(self) -> None:
        """Evict the model from memory (keep_alive=0), for a cold-load measurement."""
        status, payload = self.transport(f"{self.host}/api/generate", {"Content-Type": "application/json"},
                                         {"model": self.model, "keep_alive": 0}, self.timeout)
        if not 200 <= status < 300:
            raise ProviderError(self.name, "could not unload the model", status=status or None)
