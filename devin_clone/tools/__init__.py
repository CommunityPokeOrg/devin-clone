"""Tool registry."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import Tool
from .browser import BrowseTool
from .files import EditFileTool, ReadFileTool, WriteFileTool
from .gitops import GitCommitTool, GitHubCreatePRTool, GitPushTool
from .shell import ShellTool


def default_tools(workspace_root: Path, workspace, config: Config) -> list[Tool]:
    return [
        ShellTool(workspace, config.shell_timeout, config.output_limit),
        ReadFileTool(workspace_root),
        WriteFileTool(workspace_root),
        EditFileTool(workspace_root),
        BrowseTool(config.browser_timeout, config.chrome_binary),
        GitCommitTool(workspace_root),
        GitPushTool(workspace_root, config.github_token),
        GitHubCreatePRTool(workspace_root, config.github_token,
                           config.github_api),
    ]
