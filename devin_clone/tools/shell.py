"""Shell execution tool."""

from __future__ import annotations

from typing import Any

from .base import ToolResult


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    half = limit // 2
    return (
        s[:half]
        + f"\n\n... [{len(s) - limit} chars truncated] ...\n\n"
        + s[-half:]
    )


class ShellTool:
    name = "shell"
    description = (
        "Run a shell command in the task workspace. Returns combined "
        "stdout/stderr and the exit code. Long output is truncated."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to run (executed via /bin/sh).",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (optional; a default applies).",
            },
        },
        "required": ["command"],
    }

    def __init__(self, workspace, default_timeout: int, output_limit: int):
        self.workspace = workspace
        self.default_timeout = default_timeout
        self.output_limit = output_limit

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            return ToolResult("missing or empty 'command' argument",
                              is_error=True)
        timeout = arguments.get("timeout") or self.default_timeout
        try:
            timeout = max(1, min(int(timeout), 600))
        except (TypeError, ValueError):
            timeout = self.default_timeout

        result = self.workspace.exec(command, timeout=timeout)
        output = _truncate(result.output, self.output_limit)
        return ToolResult(
            f"exit_code={result.exit_code}\n{output}",
            is_error=result.exit_code != 0,
        )
