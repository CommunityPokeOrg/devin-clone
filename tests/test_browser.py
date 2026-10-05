import http.server
import shutil
import threading

import pytest

from devin_clone.tools.browser import BrowseTool, _find_chrome, html_to_text

HTML = """<!doctype html><html><head><title>T</title>
<style>body{color:red}</style></head>
<body><h1>Hello World</h1><p>some <b>bold</b> text</p>
<script>document.body.innerHTML='JS_WAS_HERE'</script></body></html>"""

JS_HTML = """<!doctype html><html><body><div id="app"></div>
<script>document.getElementById('app').textContent='JS_WAS_HERE'</script>
</body></html>"""


@pytest.fixture
def http_server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = JS_HTML if self.path == "/js" else HTML
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_html_to_text_strips_script_and_style():
    text = html_to_text(HTML)
    assert "Hello World" in text
    assert "bold" in text
    assert "JS_WAS_HERE" not in text
    assert "color:red" not in text


def test_browse_text_mode(http_server):
    tool = BrowseTool(timeout=10)
    r = tool.run({"url": http_server + "/"})
    assert not r.is_error
    assert "status 200" in r.output
    assert "Hello World" in r.output
    assert "JS_WAS_HERE" not in r.output  # script not executed in text mode


def test_browse_rejects_bad_url():
    tool = BrowseTool(timeout=10)
    assert tool.run({"url": "file:///etc/passwd"}).is_error
    assert tool.run({"url": "notaurl"}).is_error


def test_browse_http_error(http_server):
    tool = BrowseTool(timeout=10)
    r = tool.run({"url": http_server + "/missing-for-real-404"})
    # our handler returns 200 for everything except /js is also 200; force an
    # error by hitting a closed port instead
    r2 = tool.run({"url": "http://127.0.0.1:1/"})
    assert r2.is_error


@pytest.mark.skipif(not _find_chrome(""), reason="no chrome binary")
def test_browse_dom_mode_executes_js(http_server):
    tool = BrowseTool(timeout=30)
    r = tool.run({"url": http_server + "/js", "mode": "dom"})
    assert not r.is_error, r.output
    assert "JS_WAS_HERE" in r.output  # chrome actually ran the script


def test_dom_mode_fallback_without_chrome(http_server, monkeypatch):
    monkeypatch.setattr("devin_clone.tools.browser._find_chrome",
                        lambda configured="": None)
    tool = BrowseTool(timeout=10)
    r = tool.run({"url": http_server + "/js", "mode": "dom"})
    assert not r.is_error
    assert "fell back" in r.output
    assert "JS_WAS_HERE" not in r.output
