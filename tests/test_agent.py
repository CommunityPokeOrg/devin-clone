import json

import pytest

from devin_clone.agent import AgentLoop
from devin_clone.config import Config
from devin_clone.llm import ScriptedLLM
from devin_clone.workspace import LocalWorkspace


def _make(tmp_path, script, config=None):
    config = config or Config()
    ws = LocalWorkspace(tmp_path / "ws")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    llm = ScriptedLLM(script)
    return AgentLoop(config, llm, ws, task_dir, quiet=True), ws, task_dir


def test_full_task_end_to_end(tmp_path):
    """Scripted agent: write a script, run it, report done — fully offline."""
    script = [
        {"tool_calls": [{"name": "write_file", "arguments": {
            "path": "hello.py", "content": "print('hi from agent')"}}]},
        {"tool_calls": [{"name": "shell", "arguments": {
            "command": "python3 hello.py"}}]},
        {"content": "Wrote hello.py and verified it prints 'hi from agent'."},
    ]
    loop, ws, task_dir = _make(tmp_path, script)
    result = loop.run("make a hello script")

    assert result.status == "completed"
    assert result.steps == 3
    assert (ws.path / "hello.py").exists()
    assert "verified" in result.summary

    events = [json.loads(l) for l in
              (task_dir / "events.jsonl").read_text().splitlines()]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "task_start"
    assert "tool_call" in kinds and "tool_result" in kinds
    assert kinds[-1] == "done"

    messages = json.loads((task_dir / "messages.json").read_text())
    roles = [m["role"] for m in messages]
    assert roles[0] == "system" and roles[1] == "user"
    assert "tool" in roles
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert any("hi from agent" in m["content"] for m in tool_msgs)


def test_unknown_tool_does_not_crash_loop(tmp_path):
    script = [
        {"tool_calls": [{"name": "nonsense", "arguments": {}}]},
        {"content": "ok"},
    ]
    loop, ws, task_dir = _make(tmp_path, script)
    result = loop.run("x")
    assert result.status == "completed"
    messages = json.loads((task_dir / "messages.json").read_text())
    assert any(m.get("role") == "tool" and "unknown tool" in m["content"]
               for m in messages)


def test_tool_crash_is_reported_not_raised(tmp_path):
    script = [
        {"tool_calls": [{"name": "read_file", "arguments": {}}]},
        {"content": "recovered"},
    ]
    loop, ws, task_dir = _make(tmp_path, script)
    result = loop.run("x")
    assert result.status == "completed"


def test_max_steps(tmp_path):
    script = [{"tool_calls": [{"name": "shell",
                               "arguments": {"command": "true"}}]}] * 20
    config = Config()
    config.max_steps = 3
    loop, ws, task_dir = _make(tmp_path, script, config)
    result = loop.run("x")
    assert result.status == "max_steps"
    assert result.steps == 3


def test_llm_error_persisted_and_resumable(tmp_path):
    class Boom:
        def chat(self, m, t):
            raise RuntimeError("api exploded")
    config = Config()
    ws = LocalWorkspace(tmp_path / "ws")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    loop = AgentLoop(config, Boom(), ws, task_dir, quiet=True)
    result = loop.run("do stuff")
    assert result.status == "error"
    assert "api exploded" in result.summary
    assert (task_dir / "messages.json").exists()


def test_resume_continues_message_history(tmp_path):
    """A second AgentLoop over the same task dir resumes persisted state."""
    script1 = [
        {"tool_calls": [{"name": "write_file", "arguments": {
            "path": "a.txt", "content": "A"}}]},
    ]

    class Interrupt:
        """First call replays script, second raises to simulate a crash."""

        def __init__(self):
            self.calls = 0
            self.inner = ScriptedLLM(script1)

        def chat(self, m, t):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("interrupted")
            return self.inner.chat(m, t)

    config = Config()
    ws = LocalWorkspace(tmp_path / "ws")
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    r1 = AgentLoop(config, Interrupt(), ws, task_dir, quiet=True).run("task")
    assert r1.status == "error"

    llm2 = ScriptedLLM([{"content": "resumed and done"}])
    r2 = AgentLoop(config, llm2, ws, task_dir, quiet=True).run()
    assert r2.status == "completed"
    # The resumed LLM saw the prior tool call + result in its context.
    resumed_msgs = llm2.requests[0]
    assert any(m.get("role") == "tool" for m in resumed_msgs)
    assert any("wrote a.txt" in m.get("content", "")
               for m in resumed_msgs if m.get("role") == "tool")
