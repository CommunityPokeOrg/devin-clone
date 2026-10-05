"""Git and GitHub tools.

Three tools, matching how an agent actually lands changes:

- ``git_commit`` — stage everything and commit on (optionally a new) branch.
- ``git_push`` — push a branch to a remote (token-injected https URL for
  github.com so credentials never live in the repo's git config).
- ``github_create_pr`` — open a pull request via the GitHub REST API.

The API base URL is configurable so tests can point at a local mock.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .base import ToolResult


def _git(cwd: Path, *args: str, env_extra: dict | None = None) -> ToolResult:
    import os
    env = dict(os.environ)
    env.update(env_extra or {})
    proc = subprocess.run(
        ["git", *args], cwd=cwd, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", timeout=120,
    )
    return ToolResult(proc.stdout.strip(), is_error=proc.returncode != 0)


def github_api(token: str, method: str, api_base: str, path: str,
               payload: dict | None = None) -> dict:
    """Minimal GitHub REST call. Returns parsed JSON or raises RuntimeError."""
    url = f"{api_base.rstrip('/')}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:1000]
        raise RuntimeError(f"GitHub API {method} {path} -> {e.code}: {detail}")


class GitCommitTool:
    name = "git_commit"
    description = (
        "Stage all changes in the workspace git repo and commit them. "
        "Optionally create/switch to a branch first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "branch": {"type": "string",
                       "description": "create+switch to this branch first"},
        },
        "required": ["message"],
    }

    def __init__(self, workspace_root: Path):
        self.root = Path(workspace_root)

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        message = arguments.get("message", "").strip()
        if not message:
            return ToolResult("missing 'message'", is_error=True)
        branch = arguments.get("branch")
        if branch:
            r = _git(self.root, "checkout", "-b", branch)
            if r.is_error and "already exists" not in r.output:
                return r
            if "already exists" in r.output:
                r = _git(self.root, "checkout", branch)
                if r.is_error:
                    return r
        if not (self.root / ".git").exists():
            return ToolResult("workspace is not a git repository",
                              is_error=True)
        _git(self.root, "add", "-A")
        status = _git(self.root, "status", "--porcelain")
        if not status.output.strip():
            return ToolResult("nothing to commit")
        r = _git(self.root, "commit", "-m", message)
        if r.is_error:
            return r
        head = _git(self.root, "rev-parse", "--short", "HEAD")
        return ToolResult(f"committed {head.output}: {message}")


class GitPushTool:
    name = "git_push"
    description = (
        "Push a branch to the remote. For github.com remotes the token is "
        "injected into the push URL at runtime (never stored in git config)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "branch": {"type": "string",
                       "description": "defaults to the current branch"},
            "remote": {"type": "string", "description": "default: origin"},
        },
    }

    def __init__(self, workspace_root: Path, token: str = ""):
        self.root = Path(workspace_root)
        self.token = token

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        remote = arguments.get("remote", "origin")
        branch = arguments.get("branch")
        if not branch:
            b = _git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
            if b.is_error:
                return b
            branch = b.output.strip()

        url_r = _git(self.root, "remote", "get-url", remote)
        if url_r.is_error:
            return url_r
        url = url_r.output.strip()

        push_url = url
        env_extra = {"GIT_TERMINAL_PROMPT": "0"}
        is_github = url.startswith("git@github.com:") or (
            urlparse(url).hostname or "").lower() == "github.com"
        if self.token and is_github:
            if url.startswith("git@github.com:"):
                url = "https://github.com/" + url.split(":", 1)[1]
            push_url = url.replace("https://",
                                   f"https://x-access-token:{self.token}@",
                                   1)
            r = _git(self.root, "push", "-u", push_url,
                     f"{branch}:{branch}", env_extra=env_extra)
            # Never echo the token-bearing URL back to the model.
            r.output = r.output.replace(self.token, "***")
            return r
        return _git(self.root, "push", "-u", remote, branch,
                    env_extra=env_extra)


class GitHubCreatePRTool:
    name = "github_create_pr"
    description = (
        "Open a GitHub pull request for the current (already pushed) branch "
        "via the REST API."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "description": "owner/name"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "base": {"type": "string", "description": "default: main"},
            "head": {"type": "string",
                     "description": "default: current branch"},
        },
        "required": ["repo", "title"],
    }

    def __init__(self, workspace_root: Path, token: str,
                 api_base: str = "https://api.github.com"):
        self.root = Path(workspace_root)
        self.token = token
        self.api_base = api_base

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        if not self.token:
            return ToolResult(
                "no GitHub token configured (set DEVIN_CLONE_GITHUB_TOKEN or "
                "GITHUB_TOKEN)", is_error=True)
        repo = arguments.get("repo", "")
        title = arguments.get("title", "").strip()
        if not repo or "/" not in repo or not title:
            return ToolResult("need 'repo' (owner/name) and 'title'",
                              is_error=True)
        head = arguments.get("head")
        if not head:
            b = _git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
            if b.is_error:
                return b
            head = b.output.strip()
        payload = {
            "title": title,
            "body": arguments.get("body", ""),
            "head": head,
            "base": arguments.get("base", "main"),
        }
        try:
            pr = github_api(self.token, "POST", self.api_base,
                            f"/repos/{repo}/pulls", payload)
        except RuntimeError as e:
            return ToolResult(str(e), is_error=True)
        return ToolResult(
            f"PR #{pr.get('number')}: {pr.get('html_url', '(no url)')}")
