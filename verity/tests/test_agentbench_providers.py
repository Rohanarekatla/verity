"""
B10.3′ / B10.4 (Track B, Week 10) — the provider layer, with a fake transport.

No network and no API keys: every test drives the real request building and
response parsing through a transport that records what it was sent and returns
a canned provider response (shapes from each provider's API reference).
"""

import json

import pytest

from eval.agentbench.providers import (
    BudgetExceeded,
    CostLedger,
    Message,
    PricingTable,
    ProviderError,
    UnpricedModel,
    Usage,
    default_pricing,
    make_provider,
)
from eval.agentbench.providers.timing import profile

USER = [Message(role="user", content="RootWebArea 'Shop'\n  button 'Add to cart'")]


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, headers, body, timeout):
        self.calls.append({"url": url, "headers": headers, "body": json.loads(json.dumps(body))})
        return self.responses.pop(0)


ANTHROPIC_OK = (200, {
    "id": "msg_1", "model": "claude-sonnet-5-5", "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "click('Add to cart')"}],
    "usage": {"input_tokens": 50, "output_tokens": 10,
              "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 0},
})
OPENAI_OK = (200, {
    "id": "chatcmpl-1", "model": "gpt-6.1-sol",
    "choices": [{"message": {"role": "assistant", "content": "click('Add to cart')"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3000, "completion_tokens": 12,
              "prompt_tokens_details": {"cached_tokens": 2048}},
})
OLLAMA_OK = (200, {
    "model": "qwen3:8b", "message": {"role": "assistant", "content": "click('Add to cart')"},
    "done_reason": "stop", "prompt_eval_count": 400, "eval_count": 9,
    "load_duration": 3_500_000_000, "prompt_eval_duration": 200_000_000, "eval_duration": 300_000_000,
})


def anthropic(transport, **kw):
    return make_provider("anthropic:claude-sonnet-5-5", api_key="sk-test", transport=transport,
                         sleep=lambda s: None, **kw)


# --- the interface ----------------------------------------------------------------

def test_spec_parsing_keeps_colons_in_the_model_name():
    p = make_provider("ollama:qwen3:8b", transport=FakeTransport())
    assert p.name == "ollama" and p.model == "qwen3:8b"


@pytest.mark.parametrize("spec", ["anthropic", "nope:model", ":model"])
def test_bad_specs_are_rejected(spec):
    with pytest.raises(ValueError):
        make_provider(spec)


def test_a_missing_api_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        make_provider("anthropic:claude-sonnet-5-5")


# --- Anthropic --------------------------------------------------------------------

def test_anthropic_request_uses_api_version_2026_10_21_and_no_sampling_parameters():
    t = FakeTransport(ANTHROPIC_OK)
    anthropic(t).complete(USER, system="You are a web agent.", max_tokens=64)
    call = t.calls[0]
    assert call["url"] == "https://api.anthropic.com/v1/messages"
    assert call["headers"]["anthropic-version"] == "2026-10-21"
    assert call["headers"]["authorization"] == "Bearer sk-test"
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in call["body"], "2026-10-21 rejects sampling parameters with a 400"


def test_anthropic_caches_the_system_prompt_and_the_growing_conversation():
    t = FakeTransport(ANTHROPIC_OK)
    anthropic(t).complete(USER, system="You are a web agent.")
    body = t.calls[0]["body"]
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}   # shared across episodes
    assert body["cache_control"] == {"type": "ephemeral"}                # automatic, moves each turn


def test_anthropic_without_cache_sends_no_cache_control():
    t = FakeTransport(ANTHROPIC_OK)
    anthropic(t).complete(USER, system="s", cache=False)
    assert "cache_control" not in t.calls[0]["body"]
    assert "cache_control" not in t.calls[0]["body"]["system"][0]


def test_anthropic_usage_and_cost_split_cache_writes_from_reads():
    out = anthropic(FakeTransport(ANTHROPIC_OK)).complete(USER)
    assert out.text == "click('Add to cart')"
    assert out.usage == Usage(input_tokens=50, output_tokens=10, cache_write_tokens=2000, cache_read_tokens=0)
    # Sonnet 5.5: $2 in, $10 out, $2.50 cache write (per MTok)
    assert out.cost_usd == pytest.approx((50 * 2 + 10 * 10 + 2000 * 2.5) / 1e6)
    assert out.timing.load_s is None, "a remote API has no visible load phase — None, not 0"


# --- OpenAI -----------------------------------------------------------------------

def test_openai_prompt_tokens_are_split_into_uncached_and_cached():
    t = FakeTransport(OPENAI_OK)
    out = make_provider("openai:gpt-6.1-sol", api_key="sk-test", transport=t).complete(
        USER, system="sys", seed=7, cache_key="task-17")
    body = t.calls[0]["body"]
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert body["max_completion_tokens"] == 1024 and "max_tokens" not in body
    assert body["seed"] == 7 and body["prompt_cache_key"] == "task-17"
    assert "temperature" not in body
    assert out.usage.input_tokens == 3000 - 2048 and out.usage.cache_read_tokens == 2048
    assert out.cost_usd == pytest.approx((952 * 2.0 + 2048 * 0.10 + 12 * 10.0) / 1e6)


# --- Ollama (B10.4: load vs inference) --------------------------------------------

def test_ollama_reports_load_and_inference_time_and_costs_nothing():
    t = FakeTransport(OLLAMA_OK)
    out = make_provider("ollama:qwen3:8b", transport=t, host="localhost:11434").complete(
        USER, system="sys", max_tokens=32, seed=3)
    body = t.calls[0]["body"]
    assert t.calls[0]["url"] == "http://localhost:11434/api/chat"
    assert body["stream"] is False and body["keep_alive"] == "30m"
    assert body["options"] == {"num_predict": 32, "seed": 3}
    assert out.timing.load_s == pytest.approx(3.5)
    assert out.timing.inference_s == pytest.approx(0.5)
    assert out.usage.input_tokens == 400 and out.usage.output_tokens == 9
    assert out.cost_usd == 0.0


def test_timing_profile_measures_a_cold_load_then_warm_calls():
    warm = (200, {**OLLAMA_OK[1], "load_duration": 10_000_000})
    t = FakeTransport((200, {}), OLLAMA_OK, warm, warm)  # unload, cold, warm, warm
    report = profile(make_provider("ollama:qwen3:8b", transport=t), warm=2)
    assert t.calls[0]["url"].endswith("/api/generate") and t.calls[0]["body"]["keep_alive"] == 0
    assert report["cold"]["load_s"] == pytest.approx(3.5)
    assert report["warm"]["load_s"] == pytest.approx(0.01)
    assert report["per_call_verdict"] == "load-dominant"


# --- errors and retries -----------------------------------------------------------

def test_retryable_errors_are_retried_then_succeed():
    t = FakeTransport((529, {"error": {"type": "overloaded_error", "message": "Overloaded"}}), ANTHROPIC_OK)
    out = anthropic(t).complete(USER)
    assert out.attempts == 2 and len(t.calls) == 2


def test_a_client_error_is_not_retried_and_does_not_leak_the_key():
    t = FakeTransport((400, {"error": {"message": "temperature is not supported"}}))
    with pytest.raises(ProviderError) as exc:
        anthropic(t).complete(USER)
    assert exc.value.status == 400 and not exc.value.retryable
    assert "sk-test" not in str(exc.value)
    assert len(t.calls) == 1


def test_retries_are_bounded():
    t = FakeTransport(*[(503, {})] * 3)
    with pytest.raises(ProviderError) as exc:
        anthropic(t, max_retries=2).complete(USER)
    assert exc.value.retryable and len(t.calls) == 3


# --- pricing ----------------------------------------------------------------------

def test_every_shipped_price_has_a_source_and_the_table_is_dated():
    table = default_pricing()
    assert table.as_of
    assert table.prices, "pricing.yaml lists no models"
    assert all(p.source for p in table.prices.values())


def test_haiku_long_context_tier_applies_to_the_whole_request():
    price = default_pricing().lookup("anthropic", "claude-haiku-5-5")
    short = Usage(input_tokens=100_000, output_tokens=1_000)
    long = Usage(input_tokens=100_001, output_tokens=1_000)
    assert price.cost(short) == pytest.approx((100_000 * 0.10 + 1_000 * 0.50) / 1e6)
    assert price.cost(long) == pytest.approx((100_001 * 0.50 + 1_000 * 2.50) / 1e6)


def test_an_unpriced_remote_model_is_refused_unless_explicitly_allowed():
    with pytest.raises(UnpricedModel):
        make_provider("anthropic:claude-unknown-9", api_key="k", transport=FakeTransport())
    p = make_provider("anthropic:claude-unknown-9", api_key="k", transport=FakeTransport(), allow_unpriced=True)
    assert p.price is None


def test_a_negative_price_is_a_load_error(tmp_path):
    bad = tmp_path / "pricing.yaml"
    bad.write_text("models:\n  openai:\n    m:\n      input: -1\n      output: 1\n      cache_write: 1\n"
                   "      cache_read: 1\n", encoding="utf-8")
    with pytest.raises(Exception):
        PricingTable.from_yaml(bad)


# --- the ledger: the budget is a gate ---------------------------------------------

def test_ledger_records_every_call_and_summarises_cache_share():
    ledger = CostLedger()
    p = anthropic(FakeTransport(ANTHROPIC_OK, ANTHROPIC_OK), ledger=ledger)
    p.complete(USER, tag="ep-1")
    p.complete(USER, tag="ep-2")
    s = ledger.summary()["anthropic:claude-sonnet-5-5"]
    assert s["calls"] == 2 and s["cache_write_tokens"] == 4000
    assert ledger.total_usd == pytest.approx(2 * (50 * 2 + 10 * 10 + 2000 * 2.5) / 1e6)


def test_the_cap_refuses_a_call_before_spending_not_after():
    ledger = CostLedger(cap_usd=0.0001)
    t = FakeTransport(ANTHROPIC_OK)
    with pytest.raises(BudgetExceeded):
        anthropic(t, ledger=ledger).complete(USER, max_tokens=4096)
    assert t.calls == [], "no request may be sent once the worst case could cross the cap"


def test_the_ledger_resumes_from_disk_instead_of_granting_a_fresh_budget(tmp_path):
    path = tmp_path / "ledger.jsonl"
    first = CostLedger(cap_usd=10, path=path)
    anthropic(FakeTransport(ANTHROPIC_OK), ledger=first).complete(USER)
    resumed = CostLedger(cap_usd=10, path=path)
    assert first.total_usd > 0
    assert resumed.total_usd == pytest.approx(first.total_usd)


def test_an_uncosted_call_cannot_be_recorded_under_a_cap():
    ledger = CostLedger(cap_usd=5)
    p = make_provider("anthropic:claude-unknown-9", api_key="k", transport=FakeTransport(ANTHROPIC_OK),
                      allow_unpriced=True, ledger=ledger)
    with pytest.raises(ProviderError, match="no price"):
        p.complete(USER)


def test_local_models_run_under_a_cap_because_they_are_free():
    ledger = CostLedger(cap_usd=0.0)
    out = make_provider("ollama:qwen3:8b", transport=FakeTransport(OLLAMA_OK), ledger=ledger).complete(USER)
    assert out.cost_usd == 0.0 and ledger.total_usd == 0.0
