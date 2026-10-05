```
        .        *           .                     *
   *         .        .  *        .         *
        .          *        .          .        *
   .        .        .   *       .        *
        *        .        .        *          .
```

# devin-clone

A best-effort, open-source clone of the *idea* of Devin: an autonomous AI
software engineer that takes a task prompt, works in a sandboxed workspace
with shell/file/browser/git tools, logs its progress for long-running tasks,
and can open pull requests via the GitHub API.

It is a working prototype, not a product. See **Honest status** below.

## Honest status

### Implemented and verified by the test suite (46 tests)

| Feature | Status |
|---|---|
| Agent loop (LLM ⇄ tools until a final answer) | ✅ verified end-to-end with a scripted LLM, fully offline |
| `shell` tool (exit code, combined output, timeout, truncation) | ✅ verified |
| `read_file` / `write_file` / `edit_file` (line numbers, exact-string replace, workspace-path confinement) | ✅ verified |
| `browse` tool — HTTP fetch + HTML→text | ✅ verified against a local HTTP server |
| `browse` `mode="dom"` — real headless Chrome renders JS | ✅ verified (script-injected DOM text was returned) |
| Per-task workspace directory, local backend | ✅ verified |
| Per-task workspace, Docker backend (image check + fallback) | ⚠️ code verified; container execution untested here (registry rate-limited) |
| Progress log: `events.jsonl` + live console output | ✅ verified |
| Long-running task support: `tasks` / `logs` / `resume` (state persisted per step) | ✅ verified, including crash-then-resume |
| `git_commit` / `git_push` | ✅ verified against a real local git remote |
| `github_create_pr` via GitHub REST API | ✅ verified against a mock API; **not** against real github.com (needs a token with repo scope) |
| OpenAI-compatible LLM client (any `/chat/completions` endpoint) | ✅ wire format verified against a mock server; a real-model run needs your API key |
| CLI: `run` / `tasks` / `logs` / `resume`, `pip install -e .` | ✅ verified |

### Not implemented / known gaps

- **No real-LLM tuning.** The system prompt is minimal; tool-call reliability
  depends entirely on your model. Expect to iterate.
- **No planning or sub-agents.** One flat loop, one message history.
- **No human-in-the-loop approvals.** Every tool call executes immediately.
- **Browser is read-only.** No clicking, scrolling, form fill, cookies, or
  screenshots. `dom` mode renders once and dumps the DOM.
- **Docker sandbox is one container per shell call** — no persistent container
  state between commands (the mounted workspace dir *is* the state).
- **No diff display, no structured todo list, no UI.** Console + JSONL only.
- **No CI, packaging metadata beyond `pyproject.toml`, or Windows support.**

## Install

```bash
pip install -e .
# or for tests: pip install -e ".[dev]"
```

Python 3.10+. Zero runtime dependencies (stdlib only).

## Quickstart — offline demo (no API key)

```bash
devin-clone run --scripted examples/demo_task.json \
    "Write a fizzbuzz script, run it, verify output"
devin-clone tasks
devin-clone logs <task_id>
```

`--scripted` plays back a fixed JSON script of LLM turns — this is how the
whole loop is exercised in tests without spending tokens.

## Quickstart — real run

Point it at any OpenAI-compatible chat-completions endpoint:

```bash
export DEVIN_CLONE_API_KEY=sk-...            # or OPENAI_API_KEY
export DEVIN_CLONE_API_BASE=https://api.openai.com/v1   # or your gateway
export DEVIN_CLONE_MODEL=gpt-4o              # or your model id
devin-clone run "Create a flask hello-world app and verify it runs"
```

For GitHub PRs:

```bash
export DEVIN_CLONE_GITHUB_TOKEN=ghp_...      # or GITHUB_TOKEN / GH_TOKEN
```

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `DEVIN_CLONE_API_KEY` | `$OPENAI_API_KEY` | LLM API key |
| `DEVIN_CLONE_API_BASE` | `https://api.openai.com/v1` | OpenAI-compatible endpoint |
| `DEVIN_CLONE_MODEL` | `gpt-4o` | model id |
| `DEVIN_CLONE_MAX_STEPS` | `40` | agent step limit |
| `DEVIN_CLONE_SANDBOX` | `auto` | `auto` \| `docker` \| `local` |
| `DEVIN_CLONE_DOCKER_IMAGE` | `python:3.12-slim` | image for docker workspaces |
| `DEVIN_CLONE_DOCKER_NETWORK` | `bridge` | set `none` to cut agent network access |
| `DEVIN_CLONE_HOME` | `~/.local/share/devin-clone` | task state dir |
| `DEVIN_CLONE_GITHUB_TOKEN` | `$GITHUB_TOKEN` | token for push/PR |
| `DEVIN_CLONE_CHROME` | autodetect | chrome/chromium binary for `mode="dom"` |

## Architecture

```
cli.py        argparse front end (run/tasks/logs/resume)
agent.py      the loop: LLM turn -> tool calls -> persist state -> repeat
llm.py        OpenAICompatLLM (wire client) + ScriptedLLM (offline playback)
workspace.py  LocalWorkspace / DockerWorkspace + image check & fallback
progress.py   events.jsonl progress log + console renderer
prompts.py    the system prompt
tools/        shell, files, browser, gitops -> each is {name, parameters, run()}
```

Message history is standard OpenAI tool-calling format, persisted to
`messages.json` after every step so interrupted tasks resume mid-conversation.

## Security — read this before pointing it at a real task

- **`local` sandboxing is *containment for accidents*, not a security
  boundary.** Commands run as you on your machine with a scrubbed environment
  (your API keys and tokens are *not* passed to the shell) and cwd pinned to
  the workspace — but the agent can still read/write anything your user can
  outside the workspace via absolute paths in `shell`, spawn processes, and
  reach the network. File *tools* are path-confined to the workspace; the
  shell is not and cannot be without real isolation.
- **`docker` mode is better isolation** (fresh container per command, only
  the workspace mounted, dropped env, runs as your uid) but still not a hard
  boundary — containers share your kernel and, with `bridge` networking, your
  network. Set `DEVIN_CLONE_DOCKER_NETWORK=none` to remove network access.
- **Prompt injection is unmitigated.** Any text the agent reads (files, web
  pages, command output) can instruct it to do things you didn't ask for.
  Treat every task as arbitrary code execution, because it is.
- **The GitHub token** is injected into push URLs at runtime only (never
  written to git config) and masked in tool output, but it *is* in the agent
  process's memory — use a fine-grained token scoped to the target repo.

## Development

```bash
pip install -e ".[dev]"
python -m pytest tests/ -q
```

Tests never touch the network: the LLM is scripted, GitHub is a local mock
server, browser tests hit a local HTTP server. Docker tests self-skip when no
daemon/image is available.

## License

MIT
