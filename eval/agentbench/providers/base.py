"""
B10.3′ — the provider layer's shared types (Track B, Week 10).

One interface for every model the benchmark runs — Anthropic, OpenAI, a local
Ollama — so an agent (A10.4's tree agent, B13.1′'s screen-reader agent, A14.1′'s
`verity agent-check`) never knows or cares which one it is talking to.

What every call returns is a `Completion`: the text, plus the three things the
benchmark is actually measured in — **tokens** (with prompt-cache reads and
writes kept apart, because they are priced differently), **cost** in USD, and
**timing** (wall clock always; model-load vs inference where the provider
reports it — B10.4).

Design rules:

- **No SDKs.** Plain HTTP via an injectable `transport`, like
  `verity/agents/vision_backends.py`. No new dependencies, and tests run with a
  fake transport and no network.
- **Fail loudly.** Unlike the vision backends (which abstain), a benchmark
  call that fails is an *episode error* the runner must record and exclude
  under the pre-registered rules — never a silent empty answer that would read
  as the agent failing the task. So errors raise `ProviderError`.
- **Keys never leave the request.** No header, key, or Authorization value is
  ever put in a `Completion`, an error message, or a log line (S20.1).
"""

from __future__ import annotations

import json
import time
from typing import Callable, Literal, Optional

from pydantic import BaseModel, Field

Role = Literal["user", "assistant"]


class Message(BaseModel):
    """One conversation turn. The system prompt is passed separately."""
    role: Role
    content: str


class Usage(BaseModel):
    """
    Tokens for one call, split the way providers bill them.

    `input_tokens` is input that was neither read from nor written to a prompt
    cache — Anthropic's definition. Providers that report an inclusive prompt
    count (OpenAI) are converted to this split, so `total_input` means the same
    thing everywhere.
    """
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    @property
    def total(self) -> int:
        return self.total_input + self.output_tokens


class Timing(BaseModel):
    """
    B10.4 — where the time went. `wall_s` is always measured here, around the
    HTTP call. The rest are what the provider reports, and None when it does
    not: a remote API has no model-load phase we can see, so `load_s` is None
    there, not 0.
    """
    wall_s: float = Field(ge=0)
    load_s: Optional[float] = None
    prompt_eval_s: Optional[float] = None
    generate_s: Optional[float] = None

    @property
    def inference_s(self) -> Optional[float]:
        if self.prompt_eval_s is None and self.generate_s is None:
            return None
        return (self.prompt_eval_s or 0.0) + (self.generate_s or 0.0)


class Completion(BaseModel):
    """One model call, as the benchmark records it."""
    provider: str
    model: str
    text: str
    stop_reason: Optional[str] = None
    usage: Usage
    timing: Timing
    # None only when the model has no price and the caller allowed that
    # explicitly (see pricing.py) — never silently "free".
    cost_usd: Optional[float] = None
    request_id: Optional[str] = None
    attempts: int = 1

    @property
    def cache_hit(self) -> bool:
        return self.usage.cache_read_tokens > 0


class ProviderError(Exception):
    """A call that did not produce a completion. The runner records and excludes it."""

    def __init__(self, provider: str, message: str, *, status: Optional[int] = None, retryable: bool = False):
        super().__init__(f"{provider}: {message}" + (f" (HTTP {status})" if status else ""))
        self.provider = provider
        self.status = status
        self.retryable = retryable


# (url, headers, json body, timeout seconds) -> (HTTP status, parsed JSON body)
Transport = Callable[[str, dict, dict, float], tuple[int, dict]]

RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504, 529})


def urllib_transport(url: str, headers: dict, body: dict, timeout: float) -> tuple[int, dict]:
    """The default transport: one JSON POST with the standard library."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except (ValueError, OSError):
            payload = {}
        return exc.code, payload
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # Network-level: the request may never have arrived. Retryable.
        return 0, {"error": {"message": f"network error: {exc.__class__.__name__}"}}


def error_message(body: dict) -> str:
    """The provider's own error text, without echoing anything we sent."""
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or "error")[:300]
    if isinstance(err, str):
        return err[:300]
    return "error"


def estimate_tokens(text: str) -> int:
    """
    A deliberately pessimistic token estimate for budget projection: one token
    per two characters. Real tokenisers average three to four characters per
    token on English, so this over-estimates — which is the safe direction for
    a hard spending cap.
    """
    return (len(text) + 1) // 2


class BaseProvider:
    """
    Shared call loop: budget check, bounded retries, timing, pricing, ledger.

    Subclasses implement `_request(...) -> (url, headers, body)` and
    `_parse(body, wall_s) -> Completion` (without cost).
    """

    name = "base"
    local = False

    def __init__(
        self,
        model: str,
        *,
        transport: Optional[Transport] = None,
        ledger=None,
        pricing=None,
        allow_unpriced: bool = False,
        max_retries: int = 2,
        timeout: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        from eval.agentbench.providers.pricing import UnpricedModel, default_pricing

        self.model = model
        self.transport = transport or urllib_transport
        self.ledger = ledger
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep
        self._clock = clock
        table = pricing if pricing is not None else default_pricing()
        self.price = table.lookup(self.name, model, local=self.local)
        if self.price is None and not allow_unpriced:
            # Budget is a gate, not a hope: an unpriced model would make every
            # call look free to the cap.
            raise UnpricedModel(
                f"no price for {self.name}:{model} in pricing.yaml; add it, "
                "or pass allow_unpriced=True for a run with no spending cap"
            )

    # -- subclass hooks -------------------------------------------------------

    def _request(self, messages: list[Message], *, system: Optional[str], max_tokens: int, cache: bool,
                 seed: Optional[int], cache_key: Optional[str]) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def _parse(self, body: dict, wall_s: float) -> Completion:
        raise NotImplementedError

    # -- the one public call --------------------------------------------------

    def complete(
        self,
        messages: list[Message],
        *,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        cache: bool = True,
        seed: Optional[int] = None,
        cache_key: Optional[str] = None,
        tag: Optional[str] = None,
    ) -> Completion:
        """
        Run one call. `cache` turns on prompt caching where the provider needs
        to be told (Anthropic); `seed` is passed where it is supported and
        recorded either way; `tag` labels the ledger entry (e.g. an episode id).
        """
        if not messages:
            raise ValueError("at least one message is required")
        if self.ledger is not None and self.price is not None:
            # Worst case for this call: the whole prompt billed at its dearest
            # rate (a cache WRITE costs more than plain input), every allowed
            # output token used. Refused *before* spending if it could cross
            # the cap, so the cap is never exceeded rather than merely noticed.
            prompt = (system or "") + "".join(m.content for m in messages)
            est = estimate_tokens(prompt)
            worst = Usage(cache_write_tokens=est, output_tokens=max_tokens) if cache else \
                Usage(input_tokens=est, output_tokens=max_tokens)
            projected = max(self.price.cost(worst),
                            self.price.cost(Usage(input_tokens=est, output_tokens=max_tokens)))
            self.ledger.ensure_budget(projected)

        url, headers, body = self._request(messages, system=system, max_tokens=max_tokens, cache=cache,
                                           seed=seed, cache_key=cache_key)
        attempt = 0
        while True:
            attempt += 1
            started = self._clock()
            status, payload = self.transport(url, headers, body, self.timeout)
            wall = max(0.0, self._clock() - started)
            if 200 <= status < 300:
                break
            retryable = status == 0 or status in RETRYABLE_STATUS
            if retryable and attempt <= self.max_retries:
                self._sleep(min(30.0, 2.0 ** (attempt - 1)))
                continue
            raise ProviderError(self.name, error_message(payload), status=status or None, retryable=retryable)

        completion = self._parse(payload, wall)
        completion.attempts = attempt
        if self.price is not None:
            completion.cost_usd = self.price.cost(completion.usage)
        if self.ledger is not None:
            self.ledger.record(completion, tag=tag)
        return completion
