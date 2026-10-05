"""Per-task workspaces.

Each task gets a dedicated directory the agent is told is its whole world.
Shell commands can run either directly on the host (``LocalWorkspace``) or
inside a throwaway Docker container per command (``DockerWorkspace``).

The Docker backend gives real isolation: the task directory is the only bind
mount, and the process runs as an unprivileged user with a scrubbed
environment. It is *sandboxing for accidents*, not a security boundary —
see the README for the honest caveats.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from .config import Config


@dataclass
class ExecResult:
    exit_code: int
    output: str
    timed_out: bool = False


# Environment handed to commands run by the agent. Deliberately minimal so
# host secrets (API keys, tokens) do not leak into the sandboxed shell.
def _sandbox_env(workspace: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": str(workspace),
        "LANG": "C.UTF-8",
        "TERM": "dumb",
        "GIT_AUTHOR_NAME": os.environ.get("GIT_AUTHOR_NAME", "devin-clone"),
        "GIT_AUTHOR_EMAIL": os.environ.get(
            "GIT_AUTHOR_EMAIL", "devin-clone@localhost"
        ),
        "GIT_COMMITTER_NAME": os.environ.get("GIT_COMMITTER_NAME", "devin-clone"),
        "GIT_COMMITTER_EMAIL": os.environ.get(
            "GIT_COMMITTER_EMAIL", "devin-clone@localhost"
        ),
    }


class LocalWorkspace:
    """Runs commands in the task directory on the host with a scrubbed env."""

    backend = "local"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def exec(self, command: str, timeout: int = 120) -> ExecResult:
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.path,
                env=_sandbox_env(self.path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                errors="replace",
            )
            return ExecResult(proc.returncode, proc.stdout or "")
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            return ExecResult(124, out + f"\n[timed out after {timeout}s]",
                              timed_out=True)


class DockerWorkspace:
    """Runs each command in a fresh ``docker run --rm`` container.

    The task directory is mounted at ``/work``. One container per command
    means no container state accumulates; the workspace directory itself is
    the persistent state.
    """

    backend = "docker"

    def __init__(self, path: Path, image: str, network: str = "bridge"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.image = image
        self.network = network

    def ensure_image(self) -> bool:
        """Confirm the image exists locally, pulling it once if needed."""
        try:
            present = subprocess.run(
                ["docker", "image", "inspect", self.image],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=30,
            ).returncode == 0
            if present:
                return True
            return subprocess.run(
                ["docker", "pull", self.image],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=300,
            ).returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def exec(self, command: str, timeout: int = 120) -> ExecResult:
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", self.network,
            "-v", f"{self.path}:/work",
            "-w", "/work",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/work",
            "-e", "LANG=C.UTF-8",
            "-e", "TERM=dumb",
            self.image,
            "sh", "-c", command,
        ]
        try:
            proc = subprocess.run(
                docker_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                errors="replace",
            )
            return ExecResult(proc.returncode, proc.stdout or "")
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode(errors="replace")
            # --rm containers can linger on timeout; best-effort cleanup is
            # skipped here since docker kills them via init only on newer
            # versions. Honest limitation, noted in README.
            return ExecResult(124, out + f"\n[timed out after {timeout}s]",
                              timed_out=True)


def docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def make_workspace(config: Config, path: Path | None = None):
    """Pick a workspace backend per config.sandbox, with honest fallback."""
    path = path or Path.cwd() / f"workspace-{uuid.uuid4().hex[:8]}"
    mode = config.sandbox
    if mode == "docker" or (mode == "auto" and docker_available()):
        if not docker_available():
            raise RuntimeError(
                "DEVIN_CLONE_SANDBOX=docker but the docker daemon is not "
                "reachable"
            )
        ws = DockerWorkspace(path, config.docker_image,
                             config.docker_network)
        if ws.ensure_image():
            return ws
        if mode == "docker":
            raise RuntimeError(
                f"DEVIN_CLONE_SANDBOX=docker but image "
                f"'{config.docker_image}' is not available locally and "
                f"could not be pulled"
            )
        print(f"[devin-clone] docker image '{config.docker_image}' "
              f"unavailable; falling back to local workspace",
              file=sys.stderr)
    return LocalWorkspace(path)
