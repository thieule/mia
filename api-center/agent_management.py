"""API Center — quản lý agent trong MySQL + scaffold thư mục triển khai (copy mẫu từ ``agents/ai-tech``)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

_REPO_ROOT_CACHE: Path | None = None

# ``agents/`` gồm ``core``, ``ai-tools`` và các triển khai ``ai-*``.
AGENTS_DEPLOYMENTS_DIR = "agents"


def agents_deploy_dir(repo_root: Path) -> Path:
    return repo_root / AGENTS_DEPLOYMENTS_DIR


def agent_workspace_rel(folder_name: str) -> str:
    return f"{AGENTS_DEPLOYMENTS_DIR}/{folder_name}/workspace"


def agent_config_rel(folder_name: str) -> str:
    return f"{AGENTS_DEPLOYMENTS_DIR}/{folder_name}/config/config.json"


def repo_root_from_api_center(api_center_dir: Path) -> Path:
    return api_center_dir.resolve().parent


from agent_db import (  # noqa: E402 — shared Mia agent DB URL (database `agent`)
    db_connect_kwargs,
    ensure_agent_db_env_defaults,
    parse_mysql_url,
    resolve_agent_database_url,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def agents_json_read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def agents_json_write(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def db_upsert_agent(
    *,
    agent_id: str,
    display_name: str,
    workspace_rel: str,
    config_rel: str | None,
    gateway_port: int | None,
    metadata: dict[str, Any],
) -> None:
    import pymysql

    kw = db_connect_kwargs()
    meta_json = json.dumps(metadata, ensure_ascii=False)
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mia_agents (id, display_name, workspace_root, config_path, gateway_port, metadata)
                VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE
                  display_name=VALUES(display_name),
                  workspace_root=VALUES(workspace_root),
                  config_path=VALUES(config_path),
                  gateway_port=VALUES(gateway_port),
                  metadata=VALUES(metadata)
                """,
                (agent_id, display_name, workspace_rel, config_rel, gateway_port, meta_json),
            )
    finally:
        conn.close()


def db_delete_agent(agent_id: str) -> None:
    import pymysql

    kw = db_connect_kwargs()
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM mia_agents WHERE id=%s", (agent_id,))
    finally:
        conn.close()


def db_list_agents() -> list[dict[str, Any]]:
    import pymysql

    kw = db_connect_kwargs()
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, display_name, workspace_root, config_path, gateway_port, metadata, "
                "created_at, updated_at FROM mia_agents ORDER BY id"
            )
            rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            meta = r[5]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except json.JSONDecodeError:
                    meta = {}
            out.append(
                {
                    "id": r[0],
                    "display_name": r[1],
                    "workspace_root": r[2],
                    "config_path": r[3],
                    "gateway_port": r[4],
                    "metadata": meta if isinstance(meta, dict) else {},
                    "created_at": str(r[6]) if r[6] is not None else None,
                    "updated_at": str(r[7]) if r[7] is not None else None,
                }
            )
        return out
    finally:
        conn.close()


def db_upsert_prompt(agent_id: str, kind: str, label: str, content: str) -> None:
    import pymysql

    kw = db_connect_kwargs()
    h = _sha256(content)
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO mia_agent_prompts (agent_id, kind, label, content_sha256, content)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE content_sha256=VALUES(content_sha256), content=VALUES(content),
                  updated_at=CURRENT_TIMESTAMP(6)
                """,
                (agent_id, kind, label, h, content),
            )
    finally:
        conn.close()


def db_delete_prompt(agent_id: str, kind: str, label: str) -> int:
    import pymysql

    kw = db_connect_kwargs()
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM mia_agent_prompts WHERE agent_id=%s AND kind=%s AND label=%s",
                (agent_id, kind, label),
            )
            return int(cur.rowcount or 0)
    finally:
        conn.close()


def db_get_prompt(agent_id: str, kind: str, label: str) -> dict[str, Any] | None:
    import pymysql

    kw = db_connect_kwargs()
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, kind, label, content_sha256, content, updated_at
                FROM mia_agent_prompts
                WHERE agent_id=%s AND kind=%s AND label=%s
                LIMIT 1
                """,
                (agent_id, kind, label),
            )
            r = cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0],
            "kind": r[1],
            "label": r[2],
            "content_sha256": r[3],
            "content": r[4] if r[4] is not None else "",
            "updated_at": str(r[5]) if r[5] is not None else None,
        }
    finally:
        conn.close()


def db_list_prompts(agent_id: str) -> list[dict[str, Any]]:
    import pymysql

    kw = db_connect_kwargs()
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **kw)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, kind, label, content_sha256, CHAR_LENGTH(content) AS content_chars, updated_at "
                "FROM mia_agent_prompts WHERE agent_id=%s ORDER BY kind, label",
                (agent_id,),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "kind": r[1],
                "label": r[2],
                "content_sha256": r[3],
                "content_chars": r[4],
                "updated_at": str(r[5]) if r[5] is not None else None,
            }
            for r in rows
        ]
    finally:
        conn.close()


def _init_workspace_from_core_templates(workspace: Path, core_templates: Path) -> None:
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "policy").mkdir(parents=True, exist_ok=True)
    (workspace / "agent").mkdir(parents=True, exist_ok=True)
    (workspace / "agent" / "test-runs").mkdir(parents=True, exist_ok=True)
    (workspace / "skills").mkdir(parents=True, exist_ok=True)
    (workspace / "memory").mkdir(parents=True, exist_ok=True)
    for name in ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"):
        src = core_templates / name
        if src.is_file():
            (workspace / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    mem = core_templates / "memory" / "MEMORY.md"
    if mem.is_file():
        (workspace / "memory" / "MEMORY.md").write_text(mem.read_text(encoding="utf-8"), encoding="utf-8")
    hist = workspace / "memory" / "history.jsonl"
    if not hist.is_file():
        hist.write_text("", encoding="utf-8")
    policy_readme = workspace / "policy" / "README.md"
    if not policy_readme.is_file():
        policy_readme.write_text(
            "# Policy area\n\nCanonical policies; agent must not edit without approval.\n",
            encoding="utf-8",
        )
    agent_readme = workspace / "agent" / "README.md"
    if not agent_readme.is_file():
        agent_readme.write_text(
            "# Agent area\n\nDrafts and artefacts per workspace policy.\n",
            encoding="utf-8",
        )


def scaffold_agent_deployment(
    repo_root: Path,
    *,
    folder_name: str,
    template: str,
    gateway_port: int,
) -> Path:
    """Copy ``template`` (vd. ``ai-tech``) → ``repo_root/agents/folder_name``, workspace mới từ template core, sửa cổng gateway."""
    if not re.fullmatch(r"ai-[a-z0-9][a-z0-9-]*", folder_name):
        raise ValueError("folder_name must match ai-<slug> (lowercase letters, digits, hyphen).")
    base = agents_deploy_dir(repo_root)
    base.mkdir(parents=True, exist_ok=True)
    src = base / template
    dst = base / folder_name
    if not src.is_dir():
        raise ValueError(f"Template not found: {src}")
    if dst.exists():
        raise ValueError(f"Destination already exists: {dst}")
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".env", ".venv", "__pycache__", ".DS_Store", "*.pyc", ".git"),
    )
    ws = dst / "workspace"
    if ws.is_dir():
        shutil.rmtree(ws)
    tpl = agents_deploy_dir(repo_root) / "core" / "mia" / "templates"
    if not tpl.is_dir():
        raise ValueError(f"Missing core templates: {tpl}")
    _init_workspace_from_core_templates(ws, tpl)
    cfg_path = dst / "config" / "config.json"
    if not cfg_path.is_file():
        raise ValueError(f"Missing config after scaffold: {cfg_path}")
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        gw = raw.setdefault("gateway", {})
        if isinstance(gw, dict):
            gw["port"] = int(gateway_port)
        tmp = cfg_path.parent / f".config.json.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(cfg_path)
    return dst


def validate_agent_id(agent_id: str) -> str:
    aid = (agent_id or "").strip().lower()
    if not re.fullmatch(r"mia-[a-z0-9][a-z0-9-]*", aid):
        raise ValueError("agent id must match mia-<slug> (lowercase letters, digits, hyphen).")
    return aid


def default_folder_name(agent_id: str) -> str:
    return "ai-" + agent_id.removeprefix("mia-").lstrip("-")
