"""Headless browser tool.

Two modes:

- ``text`` (default): fetch the URL over HTTP and extract readable text with a
  stdlib HTML parser. Zero dependencies, works for most pages.
- ``dom``: render the page in headless Chrome (``--headless=new --dump-dom``)
  when a Chrome/Chromium binary is available, then extract text. Needed for
  JS-heavy pages. Falls back to ``text`` with a note if no Chrome is found.

This is intentionally simple — no clicking, no sessions, no screenshots.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .base import ToolResult

USER_AGENT = "devin-clone/0.1 (+https://github.com/CommunityPokeOrg/devin-clone)"
MAX_CHARS = 20_000

_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4",
                     "section", "article", "header", "footer"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self) -> str:
        import re
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass  # HTMLParser is forgiving, but never fail the tool on bad markup
    return parser.text()


def _find_chrome(configured: str = "") -> str | None:
    if configured and shutil.which(configured):
        return configured
    for name in ("google-chrome", "chromium", "chromium-browser",
                 "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


def fetch_url(url: str, timeout: int) -> tuple[int, str, str]:
    """Return (status, content_type, body). Raises on transport errors."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(4 * 1024 * 1024)
        ctype = resp.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in ctype:
            charset = ctype.split("charset=", 1)[1].split(";")[0].strip()
        return resp.status, ctype, raw.decode(charset, errors="replace")


def render_dom(url: str, chrome: str, timeout: int) -> str:
    proc = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=10000", "--dump-dom", url],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=timeout + 20, text=True, errors="replace",
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("headless chrome produced no DOM")
    return proc.stdout


class BrowseTool:
    name = "browse"
    description = (
        "Fetch a URL and return readable text. mode='dom' renders the page in "
        "headless Chrome first (needed for JavaScript-heavy pages)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "http(s) URL to fetch"},
            "mode": {
                "type": "string",
                "enum": ["text", "dom"],
                "description": "text = plain fetch (default); "
                               "dom = render in headless Chrome first",
            },
        },
        "required": ["url"],
    }

    def __init__(self, timeout: int = 30, chrome_binary: str = ""):
        self.timeout = timeout
        self.chrome_binary = chrome_binary

    def run(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return ToolResult("need an http(s) url", is_error=True)
        mode = arguments.get("mode", "text")
        try:
            if mode == "dom":
                chrome = _find_chrome(self.chrome_binary)
                if not chrome:
                    return self._text_mode(url, note="no Chrome binary found; "
                                           "fell back to text mode")
                try:
                    dom = render_dom(url, chrome, self.timeout)
                    text = html_to_text(dom)
                    return ToolResult(_clip_text(text))
                except Exception as e:
                    return self._text_mode(
                        url, note=f"dom render failed ({e}); fell back")
            return self._text_mode(url)
        except urllib.error.HTTPError as e:
            return ToolResult(f"HTTP {e.code} fetching {url}", is_error=True)
        except Exception as e:
            return ToolResult(f"fetch failed: {e}", is_error=True)

    def _text_mode(self, url: str, note: str = "") -> ToolResult:
        status, ctype, body = fetch_url(url, self.timeout)
        if "html" in ctype:
            text = html_to_text(body)
        else:
            text = body
        prefix = f"[{note}]\n" if note else ""
        return ToolResult(f"{prefix}[status {status}, {ctype}]\n"
                          f"{_clip_text(text)}")


def _clip_text(text: str) -> str:
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n... [{len(text) - MAX_CHARS} more chars]"
    return text
