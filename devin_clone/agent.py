"""The agent loop: LLM turn -> tool calls -> repeat until a final answer.

Long-running support:
- Every step appends events to ``events.jsonl`` (see progress.py).
- The full message history is persisted to ``messages.json`` after each step,
  so an interrupted task can resume where it left off.
- A task directory also records ``task.json`` (prompt, model, workspace path).
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .llm import LLMClient, Message
from .progress import ProgressLog
from .prompts import SYSTEM_PROMPT
from .tools import default_tools
from .tools.base import Tool, spec


@dataclass
class RunResult:
    task_id: str
    status: str  # "completed" | "max_steps" | "error"
    summary: str
    steps: int
    task_dir: Path


class AgentLoop:
    def __init__(self, config: Config, llm: LLMClient, workspace,
                 task_dir: Path, quiet: bool = False):
        self.config = config
        self.llm = llm
        self.workspace = workspace
        self.task_dir = Path(task_dir)
        self.log = ProgressLog(self.task_dir, quiet=quiet)
        self.tools: list[Tool] = default_tools(
            workspace.path, workspace, config)
        self._tool_map = {t.name: t for t in self.tools}
        self.messages_path = self.task_dir / "messages.json"

    # -- persistence ---------------------------------------------------------

    def _save_messages(self, messages: list[Message]) -> None:
        self.messages_path.write_text(
            json.dumps(messages, indent=1, default=str), encoding="utf-8")

    def _load_messages(self) -> list[Message] | None:
        if self.messages_path.exists():
            return json.loads(self.messages_path.read_text(encoding="utf-8"))
        return None

    # -- the loop ------------------------------------------------------------

    def run(self, task: str | None = None) -> RunResult:
        messages = self._load_messages()
        if messages is None:
            if not task:
                raise ValueError("no persisted state; a task prompt is required")
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": task},
            ]
            self.log.event("task_start", task=task,
                           workspace=str(self.workspace.path),
                           backend=self.workspace.backend,
                           model=getattr(self.llm, "model", "scripted"))
        else:
            self.log.event("task_resume", workspace=str(self.workspace.path))

        tool_specs = [spec(t) for t in self.tools]
        steps = 0
        try:
            while steps < self.config.max_steps:
                steps += 1
                self.log.event("step", step=steps,
                               max_steps=self.config.max_steps)

                turn = self.llm.chat(messages, tool_specs)
                assistant_msg: Message = {"role": "assistant"}
                if turn.content:
                    assistant_msg["content"] = turn.content
                    self.log.event("assistant", content=turn.content)
                if turn.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in turn.tool_calls
                    ]
                messages.append(assistant_msg)

                if not turn.tool_calls:
                    summary = turn.content or "(empty final message)"
                    self.log.event("done", summary=summary, steps=steps)
                    self._save_messages(messages)
                    return RunResult(
                        task_id=self.task_dir.name, status="completed",
                        summary=summary, steps=steps, task_dir=self.task_dir)

                for tc in turn.tool_calls:
                    self.log.event("tool_call", name=tc.name,
                                   arguments=tc.arguments)
                    result = self._execute(tc.name, tc.arguments)
                    self.log.event("tool_result", name=tc.name,
                                   output=result.output[:2000],
                                   is_error=result.is_error)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result.output,
                    })

                self._save_messages(messages)

            summary = f"stopped at step limit ({self.config.max_steps})"
            self.log.event("done", summary=summary, steps=steps)
            self._save_messages(messages)
            return RunResult(task_id=self.task_dir.name, status="max_steps",
                             summary=summary, steps=steps,
                             task_dir=self.task_dir)
        except Exception as e:
            self.log.event("error", message=str(e))
            self._save_messages(messages)
            return RunResult(task_id=self.task_dir.name, status="error",
                             summary=f"{type(e).__name__}: {e}", steps=steps,
                             task_dir=self.task_dir)
        finally:
            self.log.close()

    def _execute(self, name: str, arguments: dict[str, Any]):
        tool = self._tool_map.get(name)
        if tool is None:
            from .tools.base import ToolResult
            return ToolResult(f"unknown tool: {name}", is_error=True)
        try:
            return tool.run(arguments)
        except Exception as e:
            from .tools.base import ToolResult
            return ToolResult(f"tool crashed: {type(e).__name__}: {e}",
                              is_error=True)


def new_task_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
