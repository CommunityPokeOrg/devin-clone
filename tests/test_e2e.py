"""End-to-end: CLI -> OpenAICompatLLM -> mock chat server -> tools -> done.

Exercises the real HTTP wire path (not ScriptedLLM) so the OpenAI-compatible
client is verified driving an actual agent loop.
"""

import http.server
import json
import threading

import pytest

from devin_clone.cli import main


class _QueueHandler(http.server.BaseHTTPRequestHandler):
    queue = []
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _QueueHandler.requests.append(
            json.loads(self.rfile.read(length) or b"{}"))
        resp = json.dumps(_QueueHandler.queue.pop(0)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def _turn(content=None, tool_calls=None):
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return {"choices": [{"message": msg}]}


def _call(i, name, args):
    return {"id": f"call_{i}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def mock_server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _QueueHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_cli_run_against_mock_openai_endpoint(tmp_path, monkeypatch,
                                              mock_server, capsys):
    _QueueHandler.requests = []
    _QueueHandler.queue = [
        _turn(tool_calls=[_call(0, "write_file", {
            "path": "answer.txt",
            "content": "the answer is 42"})]),
        _turn(tool_calls=[_call(1, "shell", {
            "command": "cat answer.txt"})]),
        _turn(content="Wrote answer.txt and verified its contents."),
    ]

    monkeypatch.setenv("DEVIN_CLONE_API_KEY", "test-key")
    monkeypatch.setenv("DEVIN_CLONE_API_BASE", mock_server)
    monkeypatch.setenv("DEVIN_CLONE_MODEL", "mock-model")
    monkeypatch.setenv("DEVIN_CLONE_HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"

    rc = main(["run", "--workspace", str(ws),
               "write answer.txt then cat it"])
    assert rc == 0
    assert (ws / "answer.txt").read_text() == "the answer is 42"

    # Three HTTP round-trips; the third carried the tool results back.
    assert len(_QueueHandler.requests) == 3
    final_msgs = _QueueHandler.requests[2]["messages"]
    tool_msgs = [m for m in final_msgs if m.get("role") == "tool"]
    assert len(tool_msgs) == 2
    assert tool_msgs[0]["tool_call_id"] == "call_0"
    assert "wrote answer.txt" in tool_msgs[0]["content"]
    assert "the answer is 42" in tool_msgs[1]["content"]

    out = capsys.readouterr().out
    assert "status: completed" in out
