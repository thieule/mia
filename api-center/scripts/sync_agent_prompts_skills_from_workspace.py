#!/usr/bin/env python3
"""
Đồng bộ toàn bộ nội dung prompt bootstrap (AGENTS, SOUL, USER, TOOLS) và skill (SKILL.md)
từ thư mục workspace vào MySQL (bảng mia_agents, mia_agent_prompts, mia_workspace_skills).

Yêu cầu:
  - Đã chạy migration MySQL (DDL đầy đủ agent + prompt + skill + working queue + state KV):
    api-center/schema/migrate_mia_agent_prompts_skills_mysql.sql
  - Cài: pip install pymysql (hoặc dùng venv api-center đã có pymysql)

Biến môi trường (một trong các cách):
  MIA_AGENT_SYNC_DATABASE_URL   ưu tiên (vd. mysql+pymysql://app:app@127.0.0.1:3307/agile_studio)
  AGILE_DATABASE_URL            fallback (cùng URL Agile Studio hub)

Chạy từ gốc repo mia:
  python api-center/scripts/sync_agent_prompts_skills_from_workspace.py

Tuỳ chọn:
  --repo-root PATH       mặc định: cha của thư mục chứa script (…/mia)
  --agents-json PATH     mặc định: <repo-root>/api-center/agents.json
  --builtin-skills       đồng bộ thêm skill built-in từ agents/core/mia/skills (mặc định: chỉ workspace/skills)
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

BOOTSTRAP_FILES = ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md")

KIND_BY_FILE = {
    "AGENTS.md": "bootstrap_agents",
    "SOUL.md": "bootstrap_soul",
    "USER.md": "bootstrap_user",
    "TOOLS.md": "bootstrap_tools",
}


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _display_name(agent_id: str) -> str:
    s = agent_id.replace("-", " ").strip()
    return s[:1].upper() + s[1:] if s else agent_id


def _parse_database_url(url: str) -> dict[str, Any]:
    """mysql+pymysql://user:pass@host:3306/dbname → connect kwargs for pymysql."""
    u = url.strip()
    if not u:
        raise SystemExit("Missing database URL (MIA_AGENT_SYNC_DATABASE_URL or AGILE_DATABASE_URL).")
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

        for fname in BOOTSTRAP_FILES:
            fp = workspace / fname
            if not fp.is_file():
                continue
            text = fp.read_text(encoding="utf-8")
            kind = KIND_BY_FILE.get(fname, "other")
            label = fname
            rows_prompts.append(
                (agent_id, kind, label, _sha256(text), text),
            )

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
    args = ap.parse_args()
    repo_root = args.repo_root.resolve()
    agents_path = args.agents_json or (repo_root / "api-center" / "agents.json")
    if not agents_path.is_file():
        raise SystemExit(f"Missing agents.json: {agents_path}")

    connect: dict[str, Any] = {}
    if not args.dry_run:
        url = (
            os.environ.get("MIA_AGENT_SYNC_DATABASE_URL", "").strip()
            or os.environ.get("AGILE_DATABASE_URL", "").strip()
        )
        if not url:
            raise SystemExit("Set MIA_AGENT_SYNC_DATABASE_URL or AGILE_DATABASE_URL (not required with --dry-run).")
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
    )


if __name__ == "__main__":
    main()
