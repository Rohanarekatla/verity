"""
Pluggable inference backends for the vision agent.

The vision *judgments* (rubrics + schemas) live in vision.py and never change.
Where the model actually runs does change — and that is the whole point of
this module. A backend takes a system prompt, a user prompt, and some images,
and returns parsed JSON (or nothing). The agent validates that JSON against
the judgment schema and abstains on anything invalid.

Three backends, one interface:

  - AbstainBackend  — the default. Runs no model, always abstains. This is
    what keeps an un-provisioned checkout honest: every judgment is
    `unknown`, contributing nothing to the precision number rather than
    inventing one.
  - MLXBackend      — Qwen3-VL via mlx-vlm on Apple Silicon. The plan's
    primary path (Metal-native; there is no CUDA here). Lazily imported so
    the package is only required when this backend is actually selected.
  - OpenAICompatibleBackend — any server exposing the OpenAI chat-completions
    shape: a local vLLM or Ollama on an NVIDIA box, LM Studio, etc. This is
    the seam through which vLLM enters *later* as the Week 18 Linux/CUDA
    secondary path, without a line of agent code changing.

Pointing the OpenAI-compatible backend at a *remote* endpoint sends rendered
page screenshots off the machine. That crosses the project's self-hostable /
no-network constraint and its prompt-injection threat model, so it is an
ADR-level decision, not a config convenience. The default is local.

Every backend fails soft: an import error, a missing model, an unreachable
endpoint, or malformed output all resolve to "no answer", which the agent
turns into `unknown`. A vision backend that is down must never crash a scan
and must never fabricate — abstention is the only safe failure.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class VisionBackend(Protocol):
    """A source of structured judgments over images."""

    def available(self) -> bool:
        """True if this backend can actually run (deps present, model loadable)."""
        ...

    def complete_json(self, *, system: str, user: str, images: list[str]) -> Optional[dict]:
        """
        Run one judgment. Return the model's parsed JSON object, or None if the
        backend is unavailable, the call failed, or the output wasn't JSON.
        Never raises: a failure is None, which the agent reads as abstention.
        """
        ...


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------

def extract_json_object(text: str) -> Optional[dict]:
    """
    Pull the first balanced JSON object out of model text.

    Models wrap JSON in prose, markdown fences, or a leading "Sure! ...".
    We scan for the first '{' and walk to its matching '}', respecting
    strings and escapes so a '}' inside a string value doesn't end it early.
    Returns None if there is no parseable object — which becomes abstention,
    never a guess.
    """
    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _encode_image(path: str) -> Optional[str]:
    """Read an image and return a base64 data URL, or None if unreadable."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class AbstainBackend:
    """Runs nothing, always abstains. The safe default."""

    def available(self) -> bool:
        return False

    def complete_json(self, *, system: str, user: str, images: list[str]) -> Optional[dict]:
        return None


class MLXBackend:
    """
    Qwen3-VL via mlx-vlm on Apple Silicon (the plan's primary path).

    The model is loaded lazily on first use and cached — loading an 8B model
    is seconds of cost that must not be paid at import time or per call. All
    inference is wrapped so any failure (missing package, missing weights, a
    generate error) degrades to None, i.e. abstention.
    """

    def __init__(self, model_path: str, *, max_tokens: int = 512, temperature: float = 0.0):
        self.model_path = model_path
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._model = None
        self._processor = None
        self._config = None
        self._load_failed = False

    def available(self) -> bool:
        try:
            import mlx_vlm  # noqa: F401
        except ImportError:
            return False
        return not self._load_failed

    def _ensure_loaded(self) -> bool:
        if self._model is not None:
            return True
        if self._load_failed:
            return False
        try:
            from mlx_vlm import load
            from mlx_vlm.utils import load_config

            self._model, self._processor = load(self.model_path)
            self._config = load_config(self.model_path)
            return True
        except Exception:
            # Missing weights, wrong path, incompatible mlx-vlm — abstain, don't crash.
            self._load_failed = True
            return False

    def complete_json(self, *, system: str, user: str, images: list[str]) -> Optional[dict]:
        if not self._ensure_loaded():
            return None
        try:
            from mlx_vlm import generate
            from mlx_vlm.prompt_utils import apply_chat_template

            prompt = apply_chat_template(
                self._processor,
                self._config,
                f"{system}\n\n{user}\n\nRespond with a single JSON object and nothing else.",
                num_images=len(images),
            )
            output = generate(
                self._model,
                self._processor,
                prompt,
                image=images,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                verbose=False,
            )
            text = output if isinstance(output, str) else getattr(output, "text", str(output))
            return extract_json_object(text)
        except Exception:
            return None


class OpenAICompatibleBackend:
    """
    Any OpenAI chat-completions endpoint: local vLLM/Ollama on an NVIDIA box,
    LM Studio, or — deliberately behind an ADR — a remote endpoint.

    Uses urllib so no client library is required. Images are sent as base64
    data URLs in the standard `image_url` content parts.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.0,
        timeout: float = 120.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def complete_json(self, *, system: str, user: str, images: list[str]) -> Optional[dict]:
        import urllib.error
        import urllib.request

        content: list[dict] = [{"type": "text", "text": f"{user}\n\nRespond with a single JSON object and nothing else."}]
        for path in images:
            encoded = _encode_image(path)
            if encoded is None:
                return None  # can't read an image -> abstain, don't send a partial request
            content.append({"type": "image_url", "image_url": {"url": encoded}})

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"]
        except (urllib.error.URLError, TimeoutError, OSError, KeyError, IndexError, json.JSONDecodeError):
            return None
        return extract_json_object(text)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def backend_from_env() -> VisionBackend:
    """
    Choose a backend from the environment. Defaults to abstaining, so an
    un-provisioned run is honest rather than broken.

        VERITY_VISION_BACKEND = abstain | mlx | openai      (default: abstain)

        mlx:     VERITY_MLX_MODEL      (path or HF id of a Qwen3-VL mlx build)
        openai:  VERITY_VISION_BASE_URL, VERITY_VISION_MODEL,
                 VERITY_VISION_API_KEY (optional)
    """
    kind = os.environ.get("VERITY_VISION_BACKEND", "abstain").strip().lower()

    if kind == "mlx":
        model = os.environ.get("VERITY_MLX_MODEL", "mlx-community/Qwen2.5-VL-7B-Instruct-4bit")
        return MLXBackend(model)

    if kind == "openai":
        base_url = os.environ.get("VERITY_VISION_BASE_URL", "")
        model = os.environ.get("VERITY_VISION_MODEL", "")
        if not base_url or not model:
            return AbstainBackend()
        return OpenAICompatibleBackend(
            base_url=base_url,
            model=model,
            api_key=os.environ.get("VERITY_VISION_API_KEY"),
        )

    return AbstainBackend()
