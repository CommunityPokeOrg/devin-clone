import json

from devin_clone.cli import main


def test_cli_run_scripted(tmp_path, capsys):
    script = [
        {"tool_calls": [{"name": "write_file", "arguments": {
            "path": "out.txt", "content": "cli works"}}]},
        {"content": "done via cli"},
    ]
    script_path = tmp_path / "script.json"
    script_path.write_text(json.dumps(script))
    ws = tmp_path / "ws"

    rc = main(["run", "--scripted", str(script_path),
               "--workspace", str(ws), "make a file"])
    assert rc == 0
    assert (ws / "out.txt").read_text() == "cli works"
    out = capsys.readouterr().out
    assert "status: completed" in out


def test_cli_tasks_and_logs(tmp_path, capsys, monkeypatch):
    script_path = tmp_path / "s.json"
    script_path.write_text(json.dumps([{"content": "hi"}]))
    monkeypatch.setenv("DEVIN_CLONE_HOME", str(tmp_path / "home"))

    main(["run", "--scripted", str(script_path), "t1"])
    capsys.readouterr()

    assert main(["tasks"]) == 0
    listing = capsys.readouterr().out
    assert "t1" in listing

    task_id = listing.split()[0]
    assert main(["logs", task_id]) == 0
    logs = capsys.readouterr().out
    assert "task_start" in logs
    assert "done" in logs


def test_cli_requires_api_key_without_scripted(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEVIN_CLONE_API_KEY", raising=False)
    try:
        main(["run", "--workspace", str(tmp_path / "w"), "task"])
    except SystemExit as e:
        assert "API key" in str(e.code)
    else:
        raise AssertionError("expected SystemExit")


def test_cli_resume(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DEVIN_CLONE_HOME", str(tmp_path / "home"))
    # First run ends with LLM error (script exhausted) after one tool call.
    script_path = tmp_path / "s.json"
    script_path.write_text(json.dumps([
        {"tool_calls": [{"name": "write_file", "arguments": {
            "path": "x.txt", "content": "x"}}]},
    ]))
    rc = main(["run", "--scripted", str(script_path), "task1"])
    assert rc == 1  # error status
    capsys.readouterr()

    # Resume with a finishing script.
    script_path.write_text(json.dumps([{"content": "finished"}]))
    import os
    tasks_dir = tmp_path / "home" / "tasks"
    task_id = os.listdir(tasks_dir)[0]
    rc = main(["resume", task_id, "--scripted", str(script_path)])
    assert rc == 0
    assert "status: completed" in capsys.readouterr().out
