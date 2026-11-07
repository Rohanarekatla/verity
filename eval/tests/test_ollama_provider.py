from eval.agentbench.providers.ollama import OllamaProvider
from eval.agentbench.providers.base import Message


def _req(provider_kw=None, **over):
    p = OllamaProvider("qwen3:4b", **(provider_kw or {}))
    kw = {"system": None, "max_tokens": 10, "cache": False, "seed": None, "cache_key": None}
    kw.update(over)
    return p._request([Message(role="user", content="hi")], **kw)


def _body(**kw):
    return _req(provider_kw=kw)[2]


def test_format_is_sent_when_set():
    schema = {"type": "object", "required": ["old"], "properties": {"old": {"type": "string"}}}
    assert _body(format=schema)["format"] == schema


def test_format_is_omitted_by_default():
    assert "format" not in _body()


def test_targets_the_native_chat_endpoint():
    url, _, _ = _req()
    assert url == "http://localhost:11434/api/chat"


def test_num_predict_carries_max_tokens_and_keep_alive_defaults_to_30m():
    body = _req(max_tokens=64)[2]
    assert body["options"]["num_predict"] == 64
    assert body["keep_alive"] == "30m" and body["stream"] is False


def test_keep_alive_is_configurable():
    assert _body(keep_alive="5m")["keep_alive"] == "5m"


def test_think_is_sent_only_when_set():
    assert "think" not in _body()
    assert _body(think=False)["think"] is False
    assert _body(think="low")["think"] == "low"


def test_seed_goes_into_options_only_when_given():
    assert "seed" not in _req(seed=None)[2]["options"]
    assert _req(seed=7)[2]["options"]["seed"] == 7


def test_system_prompt_becomes_a_leading_system_message():
    msgs = _req(system="You are a web agent.")[2]["messages"]
    assert msgs[0] == {"role": "system", "content": "You are a web agent."}
    assert msgs[-1]["role"] == "user"


def test_bare_host_is_normalised_and_trailing_slash_stripped():
    url = OllamaProvider("qwen3:4b", host="example:11434/")._request(
        [Message(role="user", content="hi")], system=None, max_tokens=10,
        cache=False, seed=None, cache_key=None)[0]
    assert url == "http://example:11434/api/chat"


def test_host_falls_back_to_ollama_host_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://box:9999")
    assert OllamaProvider("qwen3:4b").host == "http://box:9999"


def test_parse_converts_nanosecond_durations_to_seconds_and_counts_tokens():
    c = OllamaProvider("qwen3:4b")._parse(
        {"model": "qwen3:4b", "message": {"content": "ok"}, "done_reason": "stop",
         "prompt_eval_count": 7, "eval_count": 3,
         "load_duration": 2_000_000_000, "prompt_eval_duration": 500_000_000,
         "eval_duration": 1_000_000_000},
        wall_s=4.0)
    assert c.text == "ok" and c.stop_reason == "stop"
    assert c.usage.input_tokens == 7 and c.usage.output_tokens == 3
    assert (c.timing.load_s, c.timing.prompt_eval_s, c.timing.generate_s) == (2.0, 0.5, 1.0)


def test_parse_tolerates_missing_timing_fields():
    c = OllamaProvider("qwen3:4b")._parse({"message": {"content": ""}}, wall_s=1.0)
    assert c.timing.load_s is None and c.usage.input_tokens == 0
