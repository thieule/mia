"""Con người phê duyệt bước workflow qua file (approve / reject + feedback) — không cần server riêng."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mia.utils.helpers import ensure_dir, safe_filename


def _default_approvals_root() -> Path:
    return ensure_dir(Path.cwd() / "workspace" / "approvals")


def resolve_approvals_root(data: dict[str, Any], step_ha: dict[str, Any] | None) -> Path:
    for src in (step_ha, data.get("human_approval_defaults") or data.get("humanApprovalDefaults")):
        if not isinstance(src, dict):
            continue
        raw = src.get("approval_root") or src.get("approvalRoot")
        if raw:
            return ensure_dir(Path(str(raw).strip()).expanduser().resolve())
    return _default_approvals_root()


def approval_dir_for_step(run_id: str, step_id: str, approvals_root: Path) -> Path:
    return ensure_dir(approvals_root / run_id / safe_filename(step_id))


def merge_feedback_into_instruction(
    base_instruction: str, feedback: str, step: dict[str, Any]
) -> str:
    extra = (step.get("human_approval") or {}) if isinstance(step.get("human_approval"), dict) else {}
    rej_tmpl = str(
        extra.get("reject_append_template")
        or extra.get("rejectAppendTemplate")
        or (
            "\n\n=== Phản hồi từ người duyệt (bắt buộc xử lý trước khi gửi lại) ===\n"
            "{feedback}\n"
        )
    )
    return base_instruction + rej_tmpl.format(feedback=feedback.strip())


def get_human_approval_config(step: dict[str, Any], data: dict[str, Any]) -> dict[str, Any] | None:
    ha = step.get("human_approval")
    if not ha:
        return None
    if ha is True:
        ha = {}
    if not isinstance(ha, dict):
        return None
    defaults = data.get("human_approval_defaults") or data.get("humanApprovalDefaults")
    if not isinstance(defaults, dict):
        defaults = {}
    merged: dict[str, Any] = {**defaults, **ha}
    merged.setdefault("approver_label", "Human reviewer")
    merged.setdefault("poll_interval_s", 2.0)
    merged.setdefault("max_reject_loops", 20)
    return merged


async def wait_for_decision(
    d: Path,
    *,
    poll_s: float,
) -> dict[str, Any]:
    """
    Chờ file `decision.json` trong thư mục *d*.

    Schema:
      { "action": "approve" }
      { "action": "reject", "feedback": "..." }
    """
    dec = d / "decision.json"
    # Không hết thời ở đây; có thể bổ sung `maxWaitApprovalS` trong YAML sau
    while True:
        if dec.is_file():
            try:
                raw = dec.read_text(encoding="utf-8")
                out = json.loads(raw)
            except (json.JSONDecodeError, OSError) as e:
                await asyncio.sleep(poll_s)
                continue
            if not isinstance(out, dict):
                await asyncio.sleep(poll_s)
                continue
            action = str(out.get("action", "")).strip().lower()
            if action not in ("approve", "reject"):
                await asyncio.sleep(poll_s)
                continue
            try:
                dec.unlink()
            except OSError:
                pass
            if action == "approve":
                return {"action": "approve"}
            fb = str(out.get("feedback", "")).strip()
            if not fb and action == "reject":
                # reject bắt buộc có feedback
                await asyncio.sleep(poll_s)
                continue
            return {"action": "reject", "feedback": fb}
        await asyncio.sleep(poll_s)


def write_awaiting_package(
    d: Path,
    *,
    workflow: str,
    run_id: str,
    step_id: str,
    approver_label: str,
    ai_output: str,
    iteration: int,
    role: str,
) -> None:
    inst = (
        f"To continue the pipeline: create a file named `decision.json` in this directory:\n"
        f"  {d}\n\n"
        f"Approve (JSON):\n  {{\"action\": \"approve\"}}\n\n"
        f"Reject with feedback (JSON):\n  {{\"action\": \"reject\", \"feedback\": \"...\"}}\n\n"
        f"Approver role (informational): {approver_label}\n"
        f"AI role for this step: {role}\n"
    )
    payload = {
        "workflow": workflow,
        "run_id": run_id,
        "step_id": step_id,
        "iteration": iteration,
        "approver_label": approver_label,
        "ai_role": role,
        "ai_output": ai_output,
        "directory": str(d),
        "instructions": inst,
    }
    (d / "AWAITING_REVIEW.txt").write_text(
        inst
        + "\n--- AI output (same as awaiting_review.json) ---\n"
        + ai_output,
        encoding="utf-8",
    )
    (d / "awaiting_review.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"\n[HUMAN APPROVAL] Step {step_id!r} — write decision.json under:\n  {d}\n",
        flush=True,
    )
