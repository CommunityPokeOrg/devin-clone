"""Runtime configuration for devin-clone.

Everything is driven by environment variables with CLI overrides. There is no
config file on purpose: this is a prototype, and env vars keep secrets out of
the repo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Config:
    """Resolved configuration for one agent run."""

    # LLM (OpenAI-compatible chat-completions API)
    api_base: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_API_BASE",
            os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    )
    api_key: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_API_KEY", os.environ.get("OPENAI_API_KEY", "")
        )
    )
    model: str = field(
        default_factory=lambda: os.environ.get("DEVIN_CLONE_MODEL", "gpt-4o")
    )
    max_output_tokens: int = field(
        default_factory=lambda: _env_int("DEVIN_CLONE_MAX_TOKENS", 4096)
    )

    # Agent loop
    max_steps: int = field(
        default_factory=lambda: _env_int("DEVIN_CLONE_MAX_STEPS", 40)
    )

    # Shell tool
    shell_timeout: int = field(
        default_factory=lambda: _env_int("DEVIN_CLONE_SHELL_TIMEOUT", 120)
    )
    output_limit: int = field(
        default_factory=lambda: _env_int("DEVIN_CLONE_OUTPUT_LIMIT", 30_000)
    )

    # Workspace sandboxing: "auto" | "docker" | "local"
    sandbox: str = field(
        default_factory=lambda: os.environ.get("DEVIN_CLONE_SANDBOX", "auto")
    )
    docker_image: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_DOCKER_IMAGE", "python:3.12-slim"
        )
    )
    docker_network: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_DOCKER_NETWORK", "bridge"
        )
    )

    # Task persistence (progress log + resumable state)
    tasks_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "DEVIN_CLONE_HOME",
                str(Path.home() / ".local" / "share" / "devin-clone"),
            )
        )
        / "tasks"
    )

    # GitHub
    github_token: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_GITHUB_TOKEN",
            os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN", "")),
        )
    )
    github_api: str = field(
        default_factory=lambda: os.environ.get(
            "DEVIN_CLONE_GITHUB_API", "https://api.github.com"
        )
    )

    # Browser tool
    browser_timeout: int = field(
        default_factory=lambda: _env_int("DEVIN_CLONE_BROWSER_TIMEOUT", 30)
    )
    chrome_binary: str = field(
        default_factory=lambda: os.environ.get("DEVIN_CLONE_CHROME", "")
    )
