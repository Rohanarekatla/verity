from eval.agentbench.providers.ollama import OllamaProvider
from eval.agentbench.providers.base import Message


def _body(**kw):
    p = OllamaProvider("qwen3:4b", **kw)
    _, _, body = p._request([Message(role="user", content="hi")], system=None, max_tokens=10,
                            cache=False, seed=None, cache_key=None)
    return body


def test_format_is_sent_when_set():
    schema = {"type": "object", "required": ["old"], "properties": {"old": {"type": "string"}}}
    assert _body(format=schema)["format"] == schema


def test_format_is_omitted_by_default():
    assert "format" not in _body()
