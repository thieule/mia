#!/usr/bin/env python3
"""Run Mia with `channel=workflow`: ad-hoc `--prompt`, or a YAML pipeline (`--workflow` + `--request`).

Install in the same venv (PATH alone is not enough): `pip install -r requirements.txt` or `pip install -e ../core`.
Copy a `.env` (e.g. from `../ai-tech/EXAMPLE_.env`) if keys are not already set.

  python main.py -c ..\\ai-tech\\config\\config.json --env ..\\ai-tech\\.env --prompt "List three files in workspace/agent"

  python main.py -c ..\\ai-tech\\config\\config.json --env ..\\ai-tech\\.env ^
    -w workflows\\dev-lifecycle.example.yaml --request "Order app requirements"

  python new_project.py my-product
  copy projects\\my-product\\EXAMPLE_.env projects\\my-product\\.env
  python main.py --project-dir projects\\my-product -w workflows\\pipeline.example.yaml --request "…"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
CORE = REPO / "core"


def _require_py() -> None:
    if sys.version_info < (3, 11):
        print("Required Python 3.11+.", file=sys.stderr)
        sys.exit(1)


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] == '"':
            val = val[1:-1]
        os.environ[name] = val


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Workflow runtime (OpsCenter): run mia AgentLoop with channel=workflow."
    )
    p.add_argument(
        "--config",
        "-c",
        type=Path,
        default=None,
        help="Mia config.json. Default: ai-tech, or <project-dir>/config.json when --project-dir is provided.",
    )
    p.add_argument(
        "--env",
        type=Path,
        default=None,
        help=".env. Default: workflow-runtime/.env or <project-dir>/.env.",
    )
    p.add_argument(
        "--project",
        "-p",
        type=str,
        default=None,
        help="Id session. Default: directory name (if --project-dir) or demo.",
    )
    p.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project instance directory: .env, config.json, workspace/, workflows/ (chdir to this directory).",
    )
    p.add_argument(
        "--prompt",
        type=str,
        default="",
        help="A single instruction sent to agent (workflow channel), without a YAML pipeline file.",
    )
    p.add_argument(
        "--workflow",
        "-w",
        type=Path,
        default=None,
        help="YAML pipeline (e.g. workflows/dev-lifecycle.example.yaml). Use with --request.",
    )
    p.add_argument(
        "--request",
        type=str,
        default="",
        help="Customer / ticket text for --workflow (customer request).",
    )
    p.add_argument(
        "--request-file",
        type=Path,
        default=None,
        help="Read request body from this file (UTF-8) instead of --request.",
    )
    p.add_argument(
        "--execution-mode",
        type=str,
        default=None,
        choices=("inline", "queue"),
        help="Override workflow YAML execution.mode: inline = Mia in process; queue = working_queue + poll.",
    )
    return p.parse_args()


async def _async_main(args: argparse.Namespace) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(CORE) not in sys.path:
        sys.path.insert(0, str(CORE))
    if not (CORE / "mia").is_dir():
        print(f"Not found mia at: {CORE}", file=sys.stderr)
        return 1

    try:
        from mia.config.loader import set_config_path
        from mia.facade import Mia
    except ModuleNotFoundError as e:
        print(
            f"Missing Python module {e.name!r}. In this same venv run:\n"
            f"  {sys.executable} -m pip install -e {str(CORE)!r}\n"
            f"  or: {sys.executable} -m pip install -r {ROOT / 'requirements.txt'}",
            file=sys.stderr,
        )
        return 1

    cfg_path = args.config
    if not cfg_path.is_file():
        print(f"Missing config file: {cfg_path}", file=sys.stderr)
        return 1

    from ops_center import OpsCenter, WorkflowJob

    request_text = (args.request or "").strip()
    if args.request_file and args.request_file.is_file():
        request_text = args.request_file.read_text(encoding="utf-8").strip()

    if args.workflow is not None:
        from workflow_yaml import run_workflow_from_file

        wf_path = args.workflow.resolve()
        if not wf_path.is_file():
            print(f"Missing workflow file: {wf_path}", file=sys.stderr)
            return 1
        if not request_text:
            print("Required --request or --request-file when using --workflow.", file=sys.stderr)
            return 2
        def_env = args.env.resolve() if args.env.is_file() else None
        print(
            f"Workflow: {wf_path.name}  (project={args.project}, default config={cfg_path.name})\n",
            flush=True,
        )
        try:
            results = await run_workflow_from_file(
                wf_path,
                request_text,
                args.project,
                default_config=cfg_path,
                default_env=def_env,
                repo_root=REPO,
                execution_mode=args.execution_mode,
            )
        except (FileNotFoundError, ValueError) as e:
            print(f"Workflow error: {e}", file=sys.stderr)
            return 1
        for r in results:
            q = f"  [queue_task: {r.queue_task_id}]\n" if r.queue_task_id else ""
            print(f"\n--- [{r.job_id}] ---\n{q}[session: {r.session_key}]\n{r.text}\n", flush=True)
        return 0

    set_config_path(cfg_path)
    mia = Mia.from_config(str(cfg_path))
    loop = mia._loop
    ops = OpsCenter(args.project, loop)

    try:
        if args.prompt.strip():
            job = WorkflowJob(
                id="cli-once",
                title="Ad-hoc",
                instruction=args.prompt.strip(),
            )
            r = await ops.run_job(job)
            print(f"\n[session: {r.session_key}]\n{r.text}\n", flush=True)
        else:
            print(
                "Required --prompt (a command) or --workflow with --request / --request-file.",
                file=sys.stderr,
            )
            return 2
    finally:
        await loop.close_mcp()
    return 0


def _apply_project_dir_and_env(args: argparse.Namespace) -> None:
    """Set default config/env/project id; chdir according to --project-dir."""
    if args.project is None:
        if args.project_dir is not None:
            args.project = Path(args.project_dir).resolve().name
        else:
            args.project = "demo"
    if args.project_dir is not None:
        pd = args.project_dir.resolve()
        if not pd.is_dir():
            print(f"project-dir is not a directory: {pd}", file=sys.stderr)
            sys.exit(1)
        os.chdir(pd)
    else:
        os.chdir(ROOT)

    if args.config is None:
        if args.project_dir is not None and (Path(args.project_dir).resolve() / "config.json").is_file():
            args.config = Path(args.project_dir).resolve() / "config.json"
        else:
            args.config = REPO / "ai-tech" / "config" / "config.json"
    else:
        args.config = args.config if isinstance(args.config, Path) else Path(args.config)
    args.config = args.config.resolve()

    if args.env is None:
        if args.project_dir is not None:
            args.env = (Path.cwd() / ".env").resolve()
        else:
            args.env = (ROOT / ".env").resolve()
    else:
        args.env = args.env.resolve()

    if args.env.is_file():
        _load_dotenv(args.env)


def main() -> None:
    _require_py()
    args = _parse_args()
    _apply_project_dir_and_env(args)
    raise SystemExit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
