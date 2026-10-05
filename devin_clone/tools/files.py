"""File tools: read_file, write_file, edit_file.

All paths are resolved inside the workspace; attempts to escape it are
rejected. ``edit_file`` does exact-string replacement and refuses ambiguous
edits — same contract as a careful human with sed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import ToolResult

MAX_READ_LINES = 400


def _resolve(workspace_root: Path, path: str) -> Path:
    p = (workspace_root / path).resolve()
    root = workspace_root.resolve()
    if p != root and root not in p.parents:
        raise ValueError(f"path escapes workspace: {path}")
    return p


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a file from the workspace with line numbers. Use offset/limit "
        "for large files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "1-based start line"},
            "limit": {"type": "integer", "description": "max lines"},
        },
        "required": ["path"],
    }

    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            p = _resolve(self.root, arguments.get("path", ""))
        except ValueError as e:
            return ToolResult(str(e), is_error=True)
        if not p.is_file():
            return ToolResult(f"not a file: {arguments.get('path')}",
                              is_error=True)
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            return ToolResult(f"read failed: {e}", is_error=True)
        offset = max(1, int(arguments.get("offset") or 1))
        limit = min(int(arguments.get("limit") or MAX_READ_LINES),
                    MAX_READ_LINES)
        chunk = lines[offset - 1: offset - 1 + limit]
        body = "\n".join(f"{offset + i}\t{ln}" for i, ln in enumerate(chunk))
        note = ""
        if offset - 1 + limit < len(lines):
            note = f"\n[{len(lines)} lines total; use offset to continue]"
        return ToolResult(body + note)


class WriteFileTool:
    name = "write_file"
    description = (
        "Write a file in the workspace (creates parent dirs; overwrites "
        "existing files)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content")
        if not isinstance(content, str):
            return ToolResult("missing 'content'", is_error=True)
        try:
            p = _resolve(self.root, arguments.get("path", ""))
        except ValueError as e:
            return ToolResult(str(e), is_error=True)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        except OSError as e:
            return ToolResult(f"write failed: {e}", is_error=True)
        return ToolResult(f"wrote {p.relative_to(self.root)} "
                          f"({len(content)} chars)")


class EditFileTool:
    name = "edit_file"
    description = (
        "Replace an exact string in a workspace file. old_string must occur "
        "exactly once."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        old = arguments.get("old_string")
        new = arguments.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str) or old == "":
            return ToolResult("need non-empty 'old_string' and 'new_string'",
                              is_error=True)
        try:
            p = _resolve(self.root, arguments.get("path", ""))
        except ValueError as e:
            return ToolResult(str(e), is_error=True)
        if not p.is_file():
            return ToolResult(f"not a file: {arguments.get('path')}",
                              is_error=True)
        text = p.read_text(encoding="utf-8", errors="replace")
        count = text.count(old)
        if count == 0:
            return ToolResult("old_string not found", is_error=True)
        if count > 1:
            return ToolResult(
                f"old_string occurs {count} times; make it unique",
                is_error=True,
            )
        p.write_text(text.replace(old, new, 1), encoding="utf-8")
        return ToolResult(f"edited {p.relative_to(self.root)}")
