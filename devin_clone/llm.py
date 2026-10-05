"""LLM backends.

Two implementations:

- ``OpenAICompatLLM`` talks to any OpenAI-compatible ``/chat/completions``
  endpoint (OpenAI, OpenRouter, vLLM, Ollama, LiteLLM, ...). Tool calling uses
  the standard ``tools`` / ``tool_calls`` wire format.
- ``ScriptedLLM`` plays back a fixed script of assistant turns. It exists so
  the whole agent loop can be exercised end-to-end in tests and demos without
  an API key.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

Message = dict[str, Any]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """One assistant response: free-text content and/or tool calls."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    def chat(self, messages: list[Message], tools: list[dict]) -> AssistantTurn:
        ...


class OpenAICompatLLM:
    """Minimal OpenAI-compatible chat client (stdlib only)."""

    def __init__(self, api_base: str, api_key: str, model: str,
                 max_output_tokens: int = 4096, timeout: int = 120):
        self.api_base = api_base.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.timeout = timeout

    def chat(self, messages: list[Message], tools: list[dict]) -> AssistantTurn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_output_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.api_base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:2000]
            raise RuntimeError(
                f"LLM API error {e.code} from {self.api_base}: {detail}"
            ) from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"LLM API unreachable ({self.api_base}): {e}") from e

        try:
            msg = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"Malformed LLM response: {data!r:.500}") from e

        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": fn.get("arguments", "")}
            calls.append(
                ToolCall(id=tc.get("id", f"call_{len(calls)}"),
                         name=fn.get("name", ""), arguments=args)
            )
        return AssistantTurn(
            content=msg.get("content") or "", tool_calls=calls, raw=msg
        )


class ScriptedLLM:
    """Plays back a queue of assistant turns for tests and offline demos.

    ``script`` is a list of dicts shaped like::

        {"tool_calls": [{"name": "shell", "arguments": {"command": "ls"}}]}
        {"content": "All done."}

    It may also be a callable ``(messages, tools) -> dict`` of the same shape,
    for dynamic behaviour.
    """

    def __init__(self, script: list[dict] | Callable):
        if callable(script):
            self._fn = script
            self._queue: list[dict] = []
        else:
            self._fn = None
            self._queue = list(script)
        self.requests: list[list[Message]] = []

    def chat(self, messages: list[Message], tools: list[dict]) -> AssistantTurn:
        self.requests.append(messages)
        if self._fn is not None:
            step = self._fn(messages, tools)
        else:
            if not self._queue:
                raise RuntimeError("ScriptedLLM: script exhausted")
            step = self._queue.pop(0)

        calls = [
            ToolCall(id=f"scripted_{i}", name=c["name"],
                     arguments=c.get("arguments", {}))
            for i, c in enumerate(step.get("tool_calls", []))
        ]
        return AssistantTurn(content=step.get("content", ""), tool_calls=calls,
                             raw=step)

    @classmethod
    def from_file(cls, path: str) -> "ScriptedLLM":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))
