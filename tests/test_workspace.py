import os
import subprocess

import pytest

from devin_clone.config import Config
from devin_clone.workspace import (DockerWorkspace, LocalWorkspace,
                                   docker_available, make_workspace)

# Any small image works; override with TEST_DOCKER_IMAGE when Docker Hub is
# rate-limited (e.g. quay.io/libpod/alpine).
_TEST_IMAGE = os.environ.get("TEST_DOCKER_IMAGE", "python:3.12-slim")


def _image_present(image: str) -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def test_local_exec(tmp_path):
    ws = LocalWorkspace(tmp_path)
    r = ws.exec("echo $HOME")
    assert r.exit_code == 0
    assert str(tmp_path) in r.output


def test_make_workspace_auto_falls_back_or_docker(tmp_path, monkeypatch):
    config = Config()
    monkeypatch.setenv("DEVIN_CLONE_SANDBOX", "auto")
    config.sandbox = "auto"
    ws = make_workspace(config, tmp_path / "w")
    assert ws.backend in ("local", "docker")


def test_make_workspace_local_forced(tmp_path):
    config = Config()
    config.sandbox = "local"
    ws = make_workspace(config, tmp_path / "w")
    assert isinstance(ws, LocalWorkspace)


def test_auto_falls_back_when_image_unavailable(tmp_path, monkeypatch):
    """auto mode must not silently hand every shell call to a broken docker."""
    monkeypatch.setattr(
        "devin_clone.workspace.docker_available", lambda: True)
    monkeypatch.setattr(
        "devin_clone.workspace.DockerWorkspace.ensure_image",
        lambda self: False)
    config = Config()
    config.sandbox = "auto"
    ws = make_workspace(config, tmp_path / "w")
    assert isinstance(ws, LocalWorkspace)


def test_auto_uses_docker_when_image_present(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "devin_clone.workspace.docker_available", lambda: True)
    monkeypatch.setattr(
        "devin_clone.workspace.DockerWorkspace.ensure_image",
        lambda self: True)
    config = Config()
    config.sandbox = "auto"
    ws = make_workspace(config, tmp_path / "w")
    assert isinstance(ws, DockerWorkspace)


def test_explicit_docker_raises_when_image_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "devin_clone.workspace.docker_available", lambda: True)
    monkeypatch.setattr(
        "devin_clone.workspace.DockerWorkspace.ensure_image",
        lambda self: False)
    config = Config()
    config.sandbox = "docker"
    with pytest.raises(RuntimeError, match="could not be pulled"):
        make_workspace(config, tmp_path / "w")


@pytest.mark.skipif(
    not (docker_available() and _image_present(_TEST_IMAGE)),
    reason=f"docker or {_TEST_IMAGE} image not available",
)
def test_docker_workspace_runs_command(tmp_path):
    ws = DockerWorkspace(tmp_path, _TEST_IMAGE)
    r = ws.exec("echo inside-container && id -u")
    assert r.exit_code == 0, r.output
    assert "inside-container" in r.output


@pytest.mark.skipif(
    not (docker_available() and _image_present(_TEST_IMAGE)),
    reason=f"docker or {_TEST_IMAGE} image not available",
)
def test_docker_workspace_sees_workspace_files(tmp_path):
    (tmp_path / "marker.txt").write_text("was-here")
    ws = DockerWorkspace(tmp_path, _TEST_IMAGE)
    r = ws.exec("cat marker.txt")
    assert r.exit_code == 0
    assert "was-here" in r.output
    # Writes inside the container land back on the host dir.
    r2 = ws.exec("echo made-in-container > created.txt")
    assert r2.exit_code == 0
    assert (tmp_path / "created.txt").read_text().strip() == "made-in-container"
