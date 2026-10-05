import time

from devin_clone.tools.shell import ShellTool


def test_shell_success(workspace):
    t = ShellTool(workspace, default_timeout=30, output_limit=10000)
    r = t.run({"command": "echo hello && pwd"})
    assert not r.is_error
    assert "exit_code=0" in r.output
    assert "hello" in r.output
    assert str(workspace.path) in r.output


def test_shell_failure_exit_code(workspace):
    t = ShellTool(workspace, default_timeout=30, output_limit=10000)
    r = t.run({"command": "echo oops >&2; exit 3"})
    assert r.is_error
    assert "exit_code=3" in r.output
    assert "oops" in r.output


def test_shell_timeout(workspace):
    t = ShellTool(workspace, default_timeout=30, output_limit=10000)
    start = time.time()
    r = t.run({"command": "sleep 10", "timeout": 1})
    assert time.time() - start < 8
    assert r.is_error
    assert "timed out" in r.output


def test_shell_truncates(workspace):
    t = ShellTool(workspace, default_timeout=30, output_limit=1000)
    r = t.run({"command": "python3 -c \"print('x'*5000)\""})
    assert "truncated" in r.output
    assert len(r.output) < 2500


def test_shell_env_is_scrubbed(workspace, monkeypatch):
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "hunter2")
    t = ShellTool(workspace, default_timeout=30, output_limit=10000)
    r = t.run({"command": "env"})
    assert "hunter2" not in r.output
    assert "SUPER_SECRET_TOKEN" not in r.output


def test_shell_missing_command(workspace):
    t = ShellTool(workspace, default_timeout=30, output_limit=10000)
    assert t.run({}).is_error
    assert t.run({"command": "  "}).is_error
