"""Tool plumbing shared by all agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class ToolResult:
    output: str
    is_error: bool = False


class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the arguments object

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        ...


def spec(tool: Tool) -> dict:
    """OpenAI-style tool spec for the wire."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }
