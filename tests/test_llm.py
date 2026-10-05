import http.server
import json
import threading

import pytest

from devin_clone.llm import OpenAICompatLLM, ScriptedLLM


class _Handler(http.server.BaseHTTPRequestHandler):
    next_response = {}
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        _Handler.requests.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": json.loads(self.rfile.read(length) or b"{}"),
        })
        resp = json.dumps(_Handler.next_response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_llm():
    _Handler.requests = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_openai_compat_parses_tool_calls(mock_llm):
    _Handler.next_response = {
        "choices": [{"message": {
            "content": None,
            "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "shell",
                             "arguments": "{\"command\": \"ls\"}"},
            }],
        }}],
    }
    llm = OpenAICompatLLM(mock_llm, "key123", "test-model")
    turn = llm.chat([{"role": "user", "content": "hi"}],
                    [{"type": "function", "function": {"name": "shell"}}])
    assert len(turn.tool_calls) == 1
    assert turn.tool_calls[0].name == "shell"
    assert turn.tool_calls[0].arguments == {"command": "ls"}

    req = _Handler.requests[0]
    assert req["path"] == "/chat/completions"
    assert req["auth"] == "Bearer key123"
    assert req["body"]["model"] == "test-model"
    assert req["body"]["tools"][0]["function"]["name"] == "shell"


def test_openai_compat_plain_content(mock_llm):
    _Handler.next_response = {
        "choices": [{"message": {"content": "hello", "tool_calls": []}}],
    }
    llm = OpenAICompatLLM(mock_llm, "k", "m")
    turn = llm.chat([], [])
    assert turn.content == "hello"
    assert turn.tool_calls == []


def test_openai_compat_http_error():
    llm = OpenAICompatLLM("http://127.0.0.1:1", "k", "m", timeout=5)
    with pytest.raises(RuntimeError, match="unreachable"):
        llm.chat([], [])


def test_openai_compat_bad_arguments_json(mock_llm):
    _Handler.next_response = {
        "choices": [{"message": {
            "tool_calls": [{"id": "c", "type": "function",
                            "function": {"name": "shell",
                                         "arguments": "not-json"}}],
        }}],
    }
    llm = OpenAICompatLLM(mock_llm, "k", "m")
    turn = llm.chat([], [])
    assert turn.tool_calls[0].arguments == {"_raw": "not-json"}


def test_scripted_llm_exhaustion():
    llm = ScriptedLLM([{"content": "only one"}])
    llm.chat([], [])
    with pytest.raises(RuntimeError, match="exhausted"):
        llm.chat([], [])
