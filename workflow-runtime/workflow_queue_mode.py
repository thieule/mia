"""Chạy workflow bằng cách nạp từng bước vào working_queue (JSON) của từng agent và chờ kết quả (poll)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ops_center import WorkflowResult
from workflow_yaml import (
    _resolve_config_and_env,
    _resolve_path,
    build_instruction,
    load_workflow_dict,
)


@dataclass
class WorkflowStateFile:
    run_id: str
    workflow: str
    project_id: str
    execution_mode: str
    status: str  # running | completed | failed
    started_at: str
    updated_at: str
    current_step_index: int
    total_steps: int
    customer_request: str
    working_queue_session_tag: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _load_state(p: Path) -> WorkflowStateFile:
    d = json.loads(p.read_text(encoding="utf-8"))
    return WorkflowStateFile(
        run_id=d["run_id"],
        workflow=d["workflow"],
        project_id=d["project_id"],
        execution_mode=d["execution_mode"],
        status=d["status"],
        started_at=d["started_at"],
        updated_at=d["updated_at"],
        current_step_index=d["current_step_index"],
        total_steps=d["total_steps"],
        customer_request=d["customer_request"],
        working_queue_session_tag=d["working_queue_session_tag"],
        steps=d.get("steps") or [],
    )


def resolve_agent_workspace(
    prof: dict[str, Any] | None,
    cfg: Path,
    repo_root: Path,
    workflow_dir: Path,
) -> Path:
    """
    - Nếu agent_profiles[role] có `workspace` → dùng đường dẫn (resolve).
    - Ngược lại: `.../config/config.json` → `.../workspace` (bố cục deploy ai-*/).
    """
    if prof and isinstance(prof, dict) and prof.get("workspace"):
        w = _resolve_path(repo_root, workflow_dir, str(prof["workspace"]))
        if w.is_dir():
            return w
        raise FileNotFoundError(
            f"agent_profiles: workspace không tồn tại: {w}"
        )
    cr = cfg.resolve()
    if cr.name == "config.json" and cr.parent.name == "config":
        cand = cr.parent.parent / "workspace"
        cand.mkdir(parents=True, exist_ok=True)
        return cand
    w = cr.parent / "workspace"
    w.mkdir(parents=True, exist_ok=True)
    return w


async def _wait_for_queue_outcome(
    store_base: Path,
    task_id: str,
    *,
    poll_s: float,
    timeout_s: float,
) -> tuple[str, Path, str | None, str | None]:
    """
    Chờ file xuất hiện ở done/ hoặc failed/.
    Trả: (outcome, path, result_text, err) — result_text từ JSON result_excerpt.
    """
    from mia.working_queue.models import parse_task_file

    pending = store_base / "working_queue" / "pending" / f"{task_id}.json"
    done = store_base / "working_queue" / "done" / f"{task_id}.json"
    fail = store_base / "working_queue" / "failed" / f"{task_id}.json"
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if done.is_file():
            task = parse_task_file(done.read_text(encoding="utf-8"))
            text = (task.result_excerpt or "") or ""
            return "done", done, text, None
        if fail.is_file():
            task = parse_task_file(fail.read_text(encoding="utf-8"))
            return "failed", fail, "", task.error or "unknown"
        if pending.is_file() or (store_base / "working_queue" / "processing" / f"{task_id}.json").is_file():
            await asyncio.sleep(poll_s)
            continue
        await asyncio.sleep(poll_s)
    raise TimeoutError(
        f"Hết thời chờ ({timeout_s}s) task {task_id} tại {store_base}. "
        f"Agent gateway tại đó có bật workingQueue (mia) để xử lý hàng đợi?"
    )


async def run_workflow_queue_mode(
    workflow_path: Path,
    customer_request: str,
    project_id: str,
    *,
    repo_root: Path,
    default_config: Path,
    default_env: Path | None,
) -> list[WorkflowResult]:
    from mia.working_queue import submit_task
    from mia.working_queue.store import WorkingQueueStore
    from mia.utils.helpers import ensure_dir, safe_filename

    from workflow_human_approval import (
        approval_dir_for_step,
        get_human_approval_config,
        merge_feedback_into_instruction,
        resolve_approvals_root,
        wait_for_decision,
        write_awaiting_package,
    )

    data = load_workflow_dict(workflow_path)
    wname = str(data.get("name", "workflow"))
    exec_block = data.get("execution") or {}
    if not isinstance(exec_block, dict):
        exec_block = {}
    wq_subdir = str(exec_block.get("workingQueueSubdir") or exec_block.get("working_queue_subdir") or "working_queue")
    poll = float(exec_block.get("pollIntervalS") or exec_block.get("poll_interval_s") or 2.0)
    timeout_s = float(
        exec_block.get("maxWaitPerStepS")
        or exec_block.get("max_wait_per_step_s")
        or 3_600.0
    )
    state_rel = str(exec_block.get("stateDir") or exec_block.get("state_dir") or "workspace/workflow_runs")
    state_dir = (Path.cwd() / state_rel).resolve()
    if state_dir.suffix in (".json",):
        raise ValueError("state_dir phải là thư mục, không phải file .json")
    if state_dir.name != "workflow_runs":
        state_dir = state_dir / "workflow_runs"
    state_dir = ensure_dir(state_dir)

    steps: list[dict[str, Any]] = data["steps"]  # type: ignore[assignment]
    workflow_dir = workflow_path.parent.resolve()
    dcfg = default_config.resolve()
    denv = default_env.resolve() if default_env else None
    wq_tag = f"{wname}__{safe_filename(project_id)}"
    run_id = uuid.uuid4().hex
    t_start = _now_iso()

    profs: dict[str, Any] = (data.get("agent_profiles") or {}) if isinstance(data.get("agent_profiles"), dict) else {}
    st = WorkflowStateFile(
        run_id=run_id,
        workflow=wname,
        project_id=project_id,
        execution_mode="queue",
        status="running",
        started_at=t_start,
        updated_at=t_start,
        current_step_index=0,
        total_steps=len(steps),
        customer_request=customer_request[:2000],
        working_queue_session_tag=wq_tag,
        steps=[],
    )
    state_path = state_dir / f"{run_id}.json"
    state_path.write_text(st.to_json(), encoding="utf-8")

    results: list[WorkflowResult] = []
    previous_text = ""
    for i, step in enumerate(steps):
        st.current_step_index = i
        st.updated_at = _now_iso()
        state_path.write_text(st.to_json(), encoding="utf-8")

        sid = str(step.get("id", f"step_{i}"))
        title = str(step.get("title", sid))
        ha = get_human_approval_config(step, data)
        instruction = build_instruction(
            step,
            customer_request=customer_request,
            previous_output=previous_text,
        )
        cfg, envf = _resolve_config_and_env(
            step, data, workflow_dir, repo_root, dcfg, denv
        )
        key = (step.get("agent") or step.get("role") or "").strip()
        if not key or key not in profs:
            raise ValueError(
                f"Chế độ queue: bước {sid!r} cần `role`/`agent` trùng một mục trong `agent_profiles` (để tìm workspace + config)."
            )
        prof = profs[key] if isinstance(profs[key], dict) else {}
        wspace = resolve_agent_workspace(prof, cfg, repo_root, workflow_dir)
        store = WorkingQueueStore(ensure_dir(wspace / wq_subdir))

        step_info: dict[str, Any] = {
            "step_id": sid,
            "title": title,
            "target_role": key,
            "agent_workspace": str(wspace),
            "config": str(cfg),
            "status": "running",
            "human_approval": bool(ha),
        }
        st.steps.append(step_info)
        state_path.write_text(st.to_json(), encoding="utf-8")

        reject_round = 0
        last_text = ""
        last_task_id = ""
        fpath: Path | None = None
        while True:
            ctx: dict[str, Any] = {
                "workflow": wname,
                "workflow_run_id": run_id,
                "step_id": sid,
                "step_index": i,
                "total_steps": len(steps),
                "title": title,
                "next_role": str(step.get("role", key)),
                "customer_request": (customer_request or "")[:8_000],
                "human_reject_round": reject_round,
            }
            if i > 0:
                ctx["previous_output_excerpt"] = (previous_text or "")[:16_000]

            task_id = submit_task(
                store,
                project_id=wq_tag,
                message=instruction,
                source_role=f"workflow:{key}",
                service=str(step.get("service") or "") or None,
                context=ctx,
                enqueued_by=f"workflow_runtime:{run_id}:step={sid}:r{reject_round}",
            )
            step_info["queue_task_id"] = task_id
            step_info["status"] = "queue_wait"
            st.updated_at = _now_iso()
            state_path.write_text(st.to_json(), encoding="utf-8")

            out, fpath, text, err = await _wait_for_queue_outcome(
                wspace, task_id, poll_s=poll, timeout_s=timeout_s
            )
            if out == "failed":
                step_info["status"] = "failed"
                step_info["error"] = err
                st.status = "failed"
                st.updated_at = _now_iso()
                state_path.write_text(st.to_json(), encoding="utf-8")
                raise RuntimeError(
                    f"Workflow bước {sid} thất bại (task {task_id}): {err}"
                )
            last_text = text
            last_task_id = task_id
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
                ai_output=last_text,
                iteration=reject_round + 1,
                role=str(step.get("role", key)),
            )
            dec = await wait_for_decision(
                adir, poll_s=float(ha.get("poll_interval_s", 2.0))
            )
            if str(dec.get("action")) == "approve":
                break
            feedback = str(dec.get("feedback", "")).strip()
            max_r = int(ha.get("max_reject_loops", 20))
            reject_round += 1
            if reject_round > max_r:
                step_info["status"] = "failed"
                st.status = "failed"
                st.updated_at = _now_iso()
                state_path.write_text(st.to_json(), encoding="utf-8")
                raise RuntimeError(
                    f"{sid!r}: quá số lần reject tối đa ({max_r})"
                )
            base = build_instruction(
                step,
                customer_request=customer_request,
                previous_output=previous_text,
            )
            instruction = merge_feedback_into_instruction(
                base, feedback, step
            )

        step_info["status"] = "done"
        step_info["result_path"] = str(fpath) if fpath else ""
        step_info["human_rejections"] = reject_round
        previous_text = last_text
        st.updated_at = _now_iso()
        state_path.write_text(st.to_json(), encoding="utf-8")

        sk = f"working:{safe_filename(wq_tag)}"
        job_id = f"wq:{run_id}:{sid}"
        results.append(
            WorkflowResult(
                job_id=job_id,
                text=last_text,
                session_key=sk,
                queue_task_id=last_task_id,
            )
        )

    st.status = "completed"
    st.current_step_index = len(steps)
    st.updated_at = _now_iso()
    state_path.write_text(st.to_json(), encoding="utf-8")
    return results
