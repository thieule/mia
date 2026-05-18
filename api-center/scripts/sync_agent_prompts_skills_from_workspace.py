#!/usr/bin/env python3
"""
Đồng bộ toàn bộ file ``*.md`` trong workspace mỗi agent (prompt) và ``skills/*/SKILL.md``
vào MySQL (``mia_agents``, ``mia_agent_prompts``, ``mia_workspace_skills``).

Prompt: mọi ``.md`` dưới workspace trừ ``skills/``, ``working_queue/``, ``sessions/``.
``kind`` + ``label`` (đường dẫn tương đối, vd. ``policy/PRE_IMPLEMENTATION_APPROVAL.md``).
File gốc AGENTS/SOUL/USER/TOOLS vẫn dùng kind ``bootstrap_*`` như trước.

Yêu cầu:
  - Đã chạy migration MySQL (DDL đầy đủ agent + prompt + skill + working queue + state KV):
    api-center/schema/migrate_mia_agent_prompts_skills_mysql.sql
  - Cài: pip install pymysql (hoặc dùng venv api-center đã có pymysql)

Biến môi trường (một trong các cách):
  MIA_AGENT_DATABASE_URL        ưu tiên — database ``agent`` (không dùng agile_studio)
  API_CENTER_AGENT_DB_URL       alias
  MIA_AGENT_SYNC_DATABASE_URL   alias (sync script)

Chạy từ gốc repo mia:
  python api-center/scripts/sync_agent_prompts_skills_from_workspace.py

Tuỳ chọn:
  --repo-root PATH       mặc định: cha của thư mục chứa script (…/mia)
  --agents-json PATH     mặc định: <repo-root>/api-center/agents.json
  --builtin-skills       đồng bộ thêm skill built-in từ agents/core/mia/skills (mặc định: chỉ workspace/skills)
  --prune-prompts        xóa bản ghi mia_agent_prompts không còn file tương ứng trong workspace
  --dry-run              chỉ in thống kê, không ghi DB
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

KIND_BY_FILE = {
    "AGENTS.md": "bootstrap_agents",
    "SOUL.md": "bootstrap_soul",
    "USER.md": "bootstrap_user",
    "TOOLS.md": "bootstrap_tools",
}

# Thư mục không quét prompt (skills → bảng riêng; runtime → không phải prompt tĩnh).
_PROMPT_SKIP_DIR_NAMES = frozenset({"skills", "working_queue", "sessions", ".git", "__pycache__"})

_MAX_LABEL_LEN = 255


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _display_name(agent_id: str) -> str:
    s = agent_id.replace("-", " ").strip()
    return s[:1].upper() + s[1:] if s else agent_id


def _parse_database_url(url: str) -> dict[str, Any]:
    """mysql+pymysql://user:pass@host:3306/dbname → connect kwargs for pymysql."""
    u = url.strip()
    if not u:
        raise SystemExit("Missing database URL (set MIA_AGENT_DATABASE_URL to mysql+pymysql://…/agent).")
    # strip sqlalchemy driver
    if "://" in u:
        _, rest = u.split("://", 1)
    else:
        rest = u
    # user:pass@host:port/db
    auth_host, _, db = rest.rpartition("/")
    db = db.split("?")[0]
    if "@" in auth_host:
        auth, hostport = auth_host.rsplit("@", 1)
    else:
        auth, hostport = "", auth_host
    if ":" in auth:
        user, password = auth.split(":", 1)
    else:
        user, password = auth, ""
    host = hostport
    port = 3306
    if hostport.startswith("["):
        m = re.match(r"^\[([^\]]+)\](?::(\d+))?$", hostport)
        if m:
            host = m.group(1)
            if m.group(2):
                port = int(m.group(2))
    elif ":" in hostport:
        hp, p = hostport.rsplit(":", 1)
        if p.isdigit():
            host, port = hp, int(p)
        else:
            host = hostport
    return {"host": host, "port": port, "user": user, "password": password, "database": db}


def _prompt_kind_and_label(workspace: Path, file_path: Path) -> tuple[str, str]:
    """Map workspace-relative path → (kind, label) for ``mia_agent_prompts``."""
    rel = file_path.relative_to(workspace).as_posix()
    name = file_path.name
    if name in KIND_BY_FILE:
        return KIND_BY_FILE[name], name
    if rel.startswith("memory/"):
        return "memory", rel
    if rel.startswith("policy/"):
        return "policy", rel
    if rel.startswith("project/"):
        return "project", rel
    if rel.startswith("projects/"):
        return "projects", rel
    if rel.startswith("docs/"):
        return "docs", rel
    if rel.startswith("agent/"):
        return "agent", rel
    if name == "HEARTBEAT.md":
        return "heartbeat", rel
    if rel == "README.md":
        return "workspace", rel
    return "other", rel


def _label_for_db(label: str) -> str:
    if len(label) <= _MAX_LABEL_LEN:
        return label
    return label[-_MAX_LABEL_LEN:]


def _iter_workspace_prompt_files(workspace: Path) -> list[Path]:
    """All prompt ``*.md`` under workspace except skipped runtime dirs."""
    if not workspace.is_dir():
        return []
    files: list[Path] = []
    for fp in workspace.rglob("*.md"):
        if not fp.is_file():
            continue
        try:
            rel = fp.relative_to(workspace)
        except ValueError:
            continue
        if any(part in _PROMPT_SKIP_DIR_NAMES for part in rel.parts):
            continue
        files.append(fp)
    return sorted(files, key=lambda p: p.relative_to(workspace).as_posix())


def _iter_workspace_skills(skills_dir: Path) -> list[tuple[str, Path]]:
    out: list[tuple[str, Path]] = []
    if not skills_dir.is_dir():
        return out
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        f = d / "SKILL.md"
        if f.is_file():
            out.append((d.name, f))
    return out


def _load_agents(agents_path: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(agents_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Invalid agents.json: expected object, got {type(data)}")
    return data


def sync(
    *,
    repo_root: Path,
    agents_path: Path,
    connect: dict[str, Any],
    dry_run: bool,
    builtin_skills: bool,
    prune_prompts: bool,
) -> None:
    agents_map = _load_agents(agents_path)
    rows_agents: list[tuple[Any, ...]] = []
    rows_prompts: list[tuple[Any, ...]] = []
    rows_skills: list[tuple[Any, ...]] = []

    for agent_id, meta in agents_map.items():
        if not isinstance(meta, dict):
            continue
        ws_rel = str(meta.get("workspace") or "").strip()
        if not ws_rel:
            continue
        workspace = (repo_root / ws_rel).resolve()
        cfg = meta.get("config")
        cfg_path = str((repo_root / cfg).resolve()) if isinstance(cfg, str) and cfg.strip() else None
        port = meta.get("gateway_port")
        port_i = int(port) if isinstance(port, int) or (isinstance(port, str) and str(port).isdigit()) else None
        meta_json = json.dumps({k: v for k, v in meta.items() if k not in ("workspace", "config", "gateway_port")}, ensure_ascii=False)
        rows_agents.append(
            (agent_id, _display_name(agent_id), ws_rel, cfg_path, port_i, meta_json),
        )

        seen_prompt_keys: set[tuple[str, str]] = set()
        for fp in _iter_workspace_prompt_files(workspace):
            kind, label = _prompt_kind_and_label(workspace, fp)
            label = _label_for_db(label)
            key = (kind, label)
            if key in seen_prompt_keys:
                continue
            seen_prompt_keys.add(key)
            text = fp.read_text(encoding="utf-8")
            rows_prompts.append((agent_id, kind, label, _sha256(text), text))

        for name, fp in _iter_workspace_skills(workspace / "skills"):
            text = fp.read_text(encoding="utf-8")
            rows_skills.append((agent_id, name, "workspace", _sha256(text), text))

        if builtin_skills:
            builtin_root = repo_root / "agents" / "core" / "mia" / "skills"
            for name, fp in _iter_workspace_skills(builtin_root):
                text = fp.read_text(encoding="utf-8")
                rows_skills.append((agent_id, name, "builtin", _sha256(text), text))

    print(
        f"agents={len(rows_agents)} prompts={len(rows_prompts)} skills={len(rows_skills)} dry_run={dry_run}",
        flush=True,
    )
    if dry_run:
        return

    try:
        import pymysql
    except ImportError as e:
        raise SystemExit("Install pymysql: pip install pymysql") from e

    conn = pymysql.connect(
        charset="utf8mb4",
        autocommit=False,
        **connect,
    )
    try:
        with conn.cursor() as cur:
            sql_agent = """
                INSERT INTO mia_agents (id, display_name, workspace_root, config_path, gateway_port, metadata)
                VALUES (%s, %s, %s, %s, %s, CAST(%s AS JSON))
                ON DUPLICATE KEY UPDATE
                  display_name=VALUES(display_name),
                  workspace_root=VALUES(workspace_root),
                  config_path=VALUES(config_path),
                  gateway_port=VALUES(gateway_port),
                  metadata=VALUES(metadata)
            """
            for row in rows_agents:
                cur.execute(sql_agent, row)

            sql_prompt = """
                INSERT INTO mia_agent_prompts (agent_id, kind, label, content_sha256, content)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  content_sha256=VALUES(content_sha256),
                  content=VALUES(content),
                  updated_at=CURRENT_TIMESTAMP(6)
            """
            for row in rows_prompts:
                cur.execute(sql_prompt, row)

            sql_skill = """
                INSERT INTO mia_workspace_skills (agent_id, skill_name, source, body_sha256, body)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                  body_sha256=VALUES(body_sha256),
                  body=VALUES(body),
                  last_scanned_at=CURRENT_TIMESTAMP(6)
            """
            for row in rows_skills:
                cur.execute(sql_skill, row)

            if prune_prompts:
                scanned_by_agent: dict[str, set[tuple[str, str]]] = {}
                for aid, kind, label, _, _ in rows_prompts:
                    scanned_by_agent.setdefault(aid, set()).add((kind, label))
                for aid, scanned in scanned_by_agent.items():
                    cur.execute(
                        "SELECT kind, label FROM mia_agent_prompts WHERE agent_id = %s",
                        (aid,),
                    )
                    for kind, label in cur.fetchall():
                        if (kind, label) not in scanned:
                            cur.execute(
                                "DELETE FROM mia_agent_prompts WHERE agent_id=%s AND kind=%s AND label=%s",
                                (aid, kind, label),
                            )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    print("Sync committed.", flush=True)


def main() -> None:
    here = Path(__file__).resolve()
    default_root = here.parents[2]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=default_root)
    ap.add_argument("--agents-json", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--builtin-skills",
        action="store_true",
        help="Also load agents/core/mia/skills into mia_workspace_skills per agent (large duplicate).",
    )
    ap.add_argument(
        "--prune-prompts",
        action="store_true",
        help="Remove mia_agent_prompts rows with no matching workspace file after sync.",
    )
    args = ap.parse_args()
    repo_root = args.repo_root.resolve()
    agents_path = args.agents_json or (repo_root / "api-center" / "agents.json")
    if not agents_path.is_file():
        raise SystemExit(f"Missing agents.json: {agents_path}")

    connect: dict[str, Any] = {}
    if not args.dry_run:
        url = (
            os.environ.get("MIA_AGENT_DATABASE_URL", "").strip()
            or os.environ.get("MIA_AGENT_SYNC_DATABASE_URL", "").strip()
            or os.environ.get("API_CENTER_AGENT_DB_URL", "").strip()
        )
        if not url:
            raise SystemExit("Set MIA_AGENT_DATABASE_URL (database agent; not required with --dry-run).")
        kw = _parse_database_url(url)
        connect = {
            "host": kw["host"],
            "port": kw["port"],
            "user": kw["user"],
            "password": kw["password"],
            "database": kw["database"],
        }

    sync(
        repo_root=repo_root,
        agents_path=agents_path,
        connect=connect,
        dry_run=args.dry_run,
        builtin_skills=args.builtin_skills,
        prune_prompts=args.prune_prompts,
    )


if __name__ == "__main__":
    main()
