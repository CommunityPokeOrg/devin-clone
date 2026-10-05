import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from devin_clone.workspace import LocalWorkspace  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test gets a fresh DEVIN_CLONE_HOME and local sandboxing."""
    monkeypatch.setenv("DEVIN_CLONE_HOME", str(tmp_path / "dchome"))
    monkeypatch.setenv("DEVIN_CLONE_SANDBOX", "local")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test Bot")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test Bot")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")


@pytest.fixture
def workspace(tmp_path):
    return LocalWorkspace(tmp_path / "ws")
