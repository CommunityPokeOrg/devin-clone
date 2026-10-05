import http.server
import json
import subprocess
import threading

import pytest

from devin_clone.tools.gitops import (GitCommitTool, GitHubCreatePRTool,
                                      GitPushTool, github_api)


def _init_repo(path):
    subprocess.run(["git", "init", "-b", "main"], cwd=path, check=True,
                   capture_output=True)
    (path / "file.txt").write_text("v1")


def test_commit_creates_commit(tmp_path):
    _init_repo(tmp_path)
    t = GitCommitTool(tmp_path)
    r = t.run({"message": "initial commit"})
    assert not r.is_error, r.output
    assert "committed" in r.output
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path,
                         capture_output=True, text=True)
    assert "initial commit" in log.stdout


def test_commit_on_new_branch(tmp_path):
    _init_repo(tmp_path)
    t = GitCommitTool(tmp_path)
    t.run({"message": "first"})
    (tmp_path / "file.txt").write_text("v2")
    r = t.run({"message": "second", "branch": "feature-x"})
    assert not r.is_error, r.output
    b = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert b.stdout.strip() == "feature-x"


def test_commit_nothing_to_commit(tmp_path):
    _init_repo(tmp_path)
    t = GitCommitTool(tmp_path)
    t.run({"message": "first"})
    r = t.run({"message": "second"})
    assert not r.is_error
    assert "nothing to commit" in r.output


def test_commit_not_a_repo(tmp_path):
    t = GitCommitTool(tmp_path / "sub")
    (tmp_path / "sub").mkdir()
    r = t.run({"message": "x"})
    assert r.is_error
    assert "not a git repository" in r.output


class _MockGitHub(http.server.BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        _MockGitHub.requests.append({
            "path": self.path,
            "auth": self.headers.get("Authorization"),
            "body": body,
        })
        resp = json.dumps({
            "number": 42,
            "html_url": "https://github.com/o/r/pull/42",
        }).encode()
        self.send_response(201)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


@pytest.fixture
def mock_github():
    _MockGitHub.requests = []
    srv = http.server.HTTPServer(("127.0.0.1", 0), _MockGitHub)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_github_api_posts_payload(mock_github):
    out = github_api("tok123", "POST", mock_github, "/repos/o/r/pulls",
                     {"title": "T"})
    assert out["number"] == 42
    req = _MockGitHub.requests[0]
    assert req["path"] == "/repos/o/r/pulls"
    assert req["auth"] == "Bearer tok123"
    assert req["body"]["title"] == "T"


def test_create_pr_tool(tmp_path, mock_github):
    _init_repo(tmp_path)
    GitCommitTool(tmp_path).run({"message": "c", "branch": "feat"})
    t = GitHubCreatePRTool(tmp_path, token="tok", api_base=mock_github)
    r = t.run({"repo": "o/r", "title": "My PR", "body": "does things"})
    assert not r.is_error, r.output
    assert "PR #42" in r.output
    req = _MockGitHub.requests[0]
    assert req["body"]["head"] == "feat"
    assert req["body"]["base"] == "main"
    assert req["body"]["title"] == "My PR"


def test_create_pr_without_token(tmp_path):
    _init_repo(tmp_path)
    t = GitHubCreatePRTool(tmp_path, token="", api_base="http://127.0.0.1:1")
    r = t.run({"repo": "o/r", "title": "x"})
    assert r.is_error
    assert "no GitHub token" in r.output


def test_push_no_token_injection_for_proxy_hosts(tmp_path, monkeypatch):
    """A remote whose HOST isn't github.com must not get the token injected,
    even if 'github.com' appears in its path (e.g. a git proxy)."""
    calls = []
    import devin_clone.tools.gitops as g

    class FakeR:
        def __init__(self, output="", is_error=False):
            self.output = output
            self.is_error = is_error

    def fake_git(cwd, *args, env_extra=None):
        calls.append(args)
        if args[:2] == ("remote", "get-url"):
            return FakeR("https://proxy.example.com/mirror/github.com/o/r.git")
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return FakeR("main")
        return FakeR("ok")

    monkeypatch.setattr(g, "_git", fake_git)
    t = g.GitPushTool(tmp_path, token="SECRET_TOK")
    r = t.run({"branch": "main"})
    assert not r.is_error
    push_args = [a for a in calls if a[0] == "push"]
    # pushed via the remote name, and no token-bearing URL was used
    assert push_args == [("push", "-u", "origin", "main")]
    assert all("SECRET_TOK" not in a for args_ in calls for a in args_)


def test_push_to_local_remote(tmp_path):
    """git_push works against a file:// remote (no GitHub needed)."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True,
                   capture_output=True)
    work = tmp_path / "work"
    work.mkdir()
    _init_repo(work)
    GitCommitTool(work).run({"message": "c"})
    subprocess.run(["git", "remote", "add", "origin", str(remote)],
                   cwd=work, check=True, capture_output=True)
    t = GitPushTool(work, token="")
    r = t.run({"branch": "main"})
    assert not r.is_error, r.output
    check = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "main"],
        capture_output=True, text=True)
    assert check.returncode == 0
