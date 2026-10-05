"""devin-clone command line interface.

Commands:
    devin-clone run "task"     start a task (foreground, prints progress)
    devin-clone tasks          list known tasks
    devin-clone logs <id>      render a task's event log
    devin-clone resume <id>    resume an interrupted task
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .agent import AgentLoop, new_task_id
from .config import Config
from .llm import OpenAICompatLLM, ScriptedLLM
from .progress import render_events
from .workspace import docker_available, make_workspace


def _build_llm(config: Config, args):
    if getattr(args, "scripted", None):
        return ScriptedLLM.from_file(args.scripted)
    if not config.api_key:
        sys.exit(
            "no LLM API key: set DEVIN_CLONE_API_KEY / OPENAI_API_KEY "
            "(any OpenAI-compatible endpoint via DEVIN_CLONE_API_BASE), or "
            "use --scripted FILE for an offline scripted run")
    return OpenAICompatLLM(config.api_base, config.api_key, config.model,
                           config.max_output_tokens)


def cmd_run(args) -> int:
    config = Config()
    if args.model:
        config.model = args.model
    if args.max_steps:
        config.max_steps = args.max_steps
    if args.sandbox:
        config.sandbox = args.sandbox

    task_id = new_task_id()
    task_dir = config.tasks_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)

    workspace = make_workspace(
        config, Path(args.workspace).resolve() if args.workspace else
        task_dir / "workspace")

    (task_dir / "task.json").write_text(json.dumps({
        "task_id": task_id,
        "task": args.task,
        "model": config.model,
        "sandbox": workspace.backend,
        "workspace": str(workspace.path),
    }, indent=1))

    llm = _build_llm(config, args)
    loop = AgentLoop(config, llm, workspace, task_dir)
    result = loop.run(args.task)
    print(f"\nstatus: {result.status} (steps={result.steps})")
    print(f"task dir: {result.task_dir}")
    print(f"summary: {result.summary}")
    return 0 if result.status == "completed" else 1


def cmd_tasks(args) -> int:
    config = Config()
    if not config.tasks_dir.exists():
        print("no tasks yet")
        return 0
    for d in sorted(config.tasks_dir.iterdir()):
        meta = d / "task.json"
        desc = ""
        if meta.exists():
            try:
                m = json.loads(meta.read_text())
                desc = f"  {m.get('task', '')[:80]}"
            except json.JSONDecodeError:
                pass
        print(f"{d.name}{desc}")
    return 0


def cmd_logs(args) -> int:
    config = Config()
    path = config.tasks_dir / args.task_id / "events.jsonl"
    if not path.exists():
        sys.exit(f"no such task: {args.task_id}")
    print(render_events(path))
    return 0


def cmd_resume(args) -> int:
    config = Config()
    task_dir = config.tasks_dir / args.task_id
    meta_path = task_dir / "task.json"
    if not meta_path.exists():
        sys.exit(f"no such task: {args.task_id}")
    meta = json.loads(meta_path.read_text())
    workspace = make_workspace(config, Path(meta["workspace"]))
    llm = _build_llm(config, args)
    loop = AgentLoop(config, llm, workspace, task_dir)
    result = loop.run()  # resumes from messages.json
    print(f"\nstatus: {result.status} (steps={result.steps})")
    print(f"summary: {result.summary}")
    return 0 if result.status == "completed" else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="devin-clone",
        description="A best-effort autonomous AI software engineer.")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a task")
    run.add_argument("task", help="task prompt for the agent")
    run.add_argument("--workspace", help="workspace dir (default: per-task dir)")
    run.add_argument("--model", help="model id (default: DEVIN_CLONE_MODEL)")
    run.add_argument("--max-steps", type=int, help="max agent steps")
    run.add_argument("--sandbox", choices=["auto", "docker", "local"],
                     help="workspace backend")
    run.add_argument("--scripted",
                     help="offline mode: JSON file of scripted LLM turns")
    run.set_defaults(fn=cmd_run)

    tasks = sub.add_parser("tasks", help="list tasks")
    tasks.set_defaults(fn=cmd_tasks)

    logs = sub.add_parser("logs", help="render a task's event log")
    logs.add_argument("task_id")
    logs.set_defaults(fn=cmd_logs)

    resume = sub.add_parser("resume", help="resume an interrupted task")
    resume.add_argument("task_id")
    resume.add_argument("--scripted",
                        help="offline mode: JSON file of scripted LLM turns")
    resume.add_argument("--model", help=argparse.SUPPRESS)
    resume.set_defaults(fn=cmd_resume)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
