"""Đọc workflow YAML, gắn từng bước tới config/agent (workspace) cụ thể, chạy qua process_direct."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from ops_center import OpsCenter, WorkflowJob, WorkflowResult

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render_template(text: str, context: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return context.get(key, m.group(0))

    return _PLACEHOLDER.sub(repl, text)


def load_workflow_dict(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore[import-untyped]
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "Cần: pip install pyyaml  (cùng venv với workflow-runtime)"
        ) from e
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "steps" not in data:
        raise ValueError(f"Workflow không hợp lệ: {path}")
    if not isinstance(data["steps"], list) or not data["steps"]:
        raise ValueError("Workflow cần có 'steps' (list không rỗng)")
    return data


def _resolve_path(repo_root: Path, workflow_dir: Path, raw: str) -> Path:
    """`raw` tương đối: thử theo thư mục file yaml, rồi theo gốc repo a-agents."""
    p = Path(raw)
    if p.is_absolute():
        return p.resolve()
    for base in (workflow_dir, repo_root):
        c = (base / p).resolve()
        if c.is_file():
            return c
    return (workflow_dir / p).resolve()


def _resolve_config_and_env(
    step: dict[str, Any],
    data: dict[str, Any],
    workflow_dir: Path,
    repo_root: Path,
    default_config: Path,
    default_env: Path | None,
) -> tuple[Path, Path | None]:
    """
    Chọn (config.json, .env) cho bước này.
    Ưu tiên: step.config > bước theo `agent` / `role` từ agent_profiles > mặc định từ CLI.
    """
    profiles: dict[str, Any] = data.get("agent_profiles") or {}
    if not isinstance(profiles, dict):
        profiles = {}

    if step.get("config"):
        cfg = _resolve_path(repo_root, workflow_dir, str(step["config"]))
        ep = step.get("env")
        env_p: Path | None = _resolve_path(repo_root, workflow_dir, str(ep)) if ep else None
        if not cfg.is_file():
            raise FileNotFoundError(f"config không tồn tại: {cfg}")
        if ep and (env_p is None or not env_p.is_file()):
            raise FileNotFoundError(f"env không tồn tại: {ep!r} -> {env_p!s}")
        return (cfg, env_p if (env_p and env_p.is_file()) else None)

    key = (step.get("agent") or step.get("role") or "").strip()
    if key and key in profiles:
        prof = profiles[key]
        if not isinstance(prof, dict) or "config" not in prof:
            raise ValueError(
                f"agent_profiles['{key}'] cần key 'config' (đường tới config.json mia)"
            )
        cfg = _resolve_path(repo_root, workflow_dir, str(prof["config"]))
        ep = prof.get("env")
        if ep:
            env_p: Path | None = _resolve_path(repo_root, workflow_dir, str(ep))
        else:
            env_p = default_env
        if not cfg.is_file():
            raise FileNotFoundError(
                f"config cho agent '{key}' không tồn tại: {cfg}"
            )
        if env_p is not None and not env_p.is_file():
            raise FileNotFoundError(
                f"env cho agent '{key}': {env_p!s} không tồn tại (thêm 'env' trong profile hoặc mặc định từ --env)"
            )
        return (cfg, env_p if (env_p and env_p.is_file()) else None)

    if not default_config.is_file():
        raise FileNotFoundError(f"default config không tồn tại: {default_config}")
    return (default_config, default_env if (default_env and default_env.is_file()) else None)


def build_instruction(
    step: dict[str, Any],
    *,
    customer_request: str,
    previous_output: str,
) -> str:
    raw = str(step.get("prompt", ""))
    include_prev = bool(step.get("include_previous", True))
    prev = previous_output if include_prev else ""
    if not include_prev and "{{previous_output}}" in raw:
        prev = ""
    ctx: dict[str, str] = {
        "customer_request": customer_request,
        "previous_output": prev or "(chưa có bước trước)",
        "role": str(step.get("role", "")),
        "step_id": str(step.get("id", "")),
    }
    return _render_template(raw, ctx).strip()


def _load_dotenv_file(path: Path) -> None:
    """Cập nhật os.environ từ file (đơn giản, tương thích main)."""
    import os

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


async def run_workflow_from_file(
    workflow_path: Path,
    customer_request: str,
    project_id: str,
    *,
    default_config: Path,
    default_env: Path | None,
    repo_root: Path,
    execution_mode: str | None = None,
) -> list[WorkflowResult]:
    """
    Mỗi bước có thể dùng config mặc định hoặc theo `agent` / `agent_profiles` / `config`+`env` trên step.
    Khi đổi config giữa các bước, MCP của AgentLoop cũ được close trước khi tạo loop mới.

    ``execution_mode``: ``inline`` (Mia trong cùng process) hoặc ``queue`` (nạp ``working_queue`` từng
    agent, poll ``done/``) — mặc định từ YAML ``execution.mode`` nếu không ghi đè ở CLI.
    """
    data = load_workflow_dict(workflow_path)
    ex = data.get("execution") or {}
    mode_src = (execution_mode or (ex.get("mode") if isinstance(ex, dict) else None) or "inline")
    mode = str(mode_src).strip().lower()
    if mode in ("queue", "working_queue", "q"):
        from workflow_queue_mode import run_workflow_queue_mode

        return await run_workflow_queue_mode(
            workflow_path,
            customer_request,
            project_id,
            repo_root=repo_root,
            default_config=default_config,
            default_env=default_env,
        )

    from mia.config.loader import set_config_path
    from mia.facade import Mia

    wname = str(data.get("name", "workflow"))
    session_cfg = data.get("session") or {}
    mode = str(session_cfg.get("mode", "per_step")).lower()
    shared_id = str(session_cfg.get("shared_id", f"{wname}-chain"))
    steps: list[dict[str, Any]] = data["steps"]  # type: ignore[assignment]
    workflow_dir = workflow_path.parent.resolve()
    dcfg = default_config.resolve()
    denv = default_env.resolve() if default_env else None

    from workflow_human_approval import (
        approval_dir_for_step,
        get_human_approval_config,
        merge_feedback_into_instruction,
        resolve_approvals_root,
        wait_for_decision,
        write_awaiting_package,
    )

    run_id = uuid.uuid4().hex
    results: list[WorkflowResult] = []
    previous_text = ""
    mia = None  # Mia
    cache_key: str | None = None

    def _key(cfg: Path, env: Path | None) -> str:
        return f"{cfg.resolve()}|{(env and env.resolve())!s}"

    try:
        for step in steps:
            sid = str(step.get("id", "step"))
            title = str(step.get("title", sid))
            if mode in ("shared_chain", "shared", "chain"):
                job_id = shared_id
            else:
                job_id = f"{wname}-{sid}"

            cfg, envf = _resolve_config_and_env(
                step, data, workflow_dir, repo_root, dcfg, denv
            )
            k = _key(cfg, envf)
            if k != cache_key:
                if mia is not None:
                    await mia._loop.close_mcp()
                if envf and envf.is_file():
                    _load_dotenv_file(envf)
                set_config_path(cfg)
                mia = Mia.from_config(str(cfg))
                cache_key = k

            if mia is None:
                raise RuntimeError("internal: no Mia instance")

            ops = OpsCenter(project_id, mia._loop)
            ha = get_human_approval_config(step, data)
            reject_round = 0
            r: WorkflowResult | None = None
            instruction = build_instruction(
                step,
                customer_request=customer_request,
                previous_output=previous_text,
            )
            while True:
                job = WorkflowJob(
                    id=job_id,
                    title=title,
                    instruction=instruction,
                    metadata={
                        "role": step.get("role"),
                        "agent": step.get("agent"),
                        "workflow": wname,
                        "config": str(cfg),
                        "human_reject_round": str(reject_round),
                    },
                )
                r_out = await ops.run_job(job)
                r = r_out
                if not ha:
                    break
                aroot = resolve_approvals_root(data, ha)
                adir = approval_dir_for_step(run_id, sid, aroot)
                (adir / "decision.json").unlink(missing_ok=True)
                approver = str(ha.get("approver_label") or "Human reviewer")
                write_awaiting_package(
                    adir,
                    workflow=wname,
                    run_id=run_id,
                    step_id=sid,
                    approver_label=approver,
                    ai_output=r.text,
                    iteration=reject_round + 1,
                    role=str(step.get("role", "")),
                )
                dec = await wait_for_decision(
                    adir, poll_s=float(ha.get("poll_interval_s", 2.0))
                )
                if dec.get("action") == "approve":
                    break
                feedback = str(dec.get("feedback", "")).strip()
                max_r = int(ha.get("max_reject_loops", 20))
                reject_round += 1
                if reject_round > max_r:
                    raise RuntimeError(
                        f"Bước {sid!r}: vượt quá số lần reject tối đa ({max_r})"
                    )
                base_inst = build_instruction(
                    step,
                    customer_request=customer_request,
                    previous_output=previous_text,
                )
                instruction = merge_feedback_into_instruction(
                    base_inst, feedback, step
                )
            if r is None:
                raise RuntimeError("internal: no workflow result for step " + sid)
            results.append(r)
            previous_text = r.text
    finally:
        if mia is not None:
            await mia._loop.close_mcp()

    return results
