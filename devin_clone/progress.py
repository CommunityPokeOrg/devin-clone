"""Progress log: append-only JSONL event stream per task.

Every meaningful thing the agent does is logged as one JSON object per line to
``<tasks_dir>/<task_id>/events.jsonl`` and echoed to stderr in a compact human
form. This is the long-running-task lifeline: a task can be tailed live,
resumed after interruption, and audited afterwards.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


class ProgressLog:
    def __init__(self, task_dir: Path, quiet: bool = False):
        self.task_dir = Path(task_dir)
        self.task_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.task_dir / "events.jsonl"
        self.quiet = quiet
        self._fh = open(self.path, "a", encoding="utf-8")

    def event(self, kind: str, **data: Any) -> None:
        record = {"ts": time.time(), "type": kind, **data}
        self._fh.write(json.dumps(record, default=str) + "\n")
        self._fh.flush()
        if not self.quiet:
            self._render(record)

    def _render(self, record: dict) -> None:
        kind = record["type"]
        line = {
            "task_start": lambda r: f"task: {r.get('task', '')}",
            "step": lambda r: f"--- step {r.get('step')}/{r.get('max_steps')}",
            "assistant": lambda r: _clip(r.get("content", ""), 400),
            "tool_call": lambda r: (
                f"$ {r.get('name')} {_clip(json.dumps(r.get('arguments', {}))[:300], 300)}"
            ),
            "tool_result": lambda r: (
                f"  -> {_clip(r.get('output', ''), 200)}"
                + (" [error]" if r.get("is_error") else "")
            ),
            "done": lambda r: f"done: {_clip(r.get('summary', ''), 400)}",
            "error": lambda r: f"ERROR: {_clip(r.get('message', ''), 400)}",
        }.get(kind)
        if line:
            print(line(record), file=sys.stderr, flush=True)

    def close(self) -> None:
        self._fh.close()


def _clip(s: str, n: int) -> str:
    s = s.replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def render_events(path: Path) -> str:
    """Render an events.jsonl file to a human-readable transcript."""
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(raw)
        except json.JSONDecodeError:
            continue
        ts = time.strftime("%H:%M:%S", time.localtime(r.get("ts", 0)))
        kind = r.get("type", "?")
        body = {k: v for k, v in r.items() if k not in ("ts", "type")}
        out.append(f"[{ts}] {kind}: {json.dumps(body, default=str)[:500]}")
    return "\n".join(out)
