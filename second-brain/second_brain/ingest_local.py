"""Quét mã trên filesystem nơi process Second Brain chạy → Neo4j + ES (cùng pipeline GitHub).

An toàn: bắt buộc `SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS` (comma-separated) — chỉ cho phép đọc dưới các gốc đó.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from second_brain.code_static_multilang import EXT_TO_LANG
from second_brain.repo_graph import (
    link_commit_to_repository,
    merge_git_repository,
    normalize_local_repo_key,
)

_log = logging.getLogger(__name__)

_SKIP_DIR_NAMES = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "dist",
        "build",
        "target",
        "out",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".tox",
        ".nox",
    }
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_allowed_roots() -> list[Path]:
    raw = (os.environ.get("SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS") or "").strip()
    if not raw:
        return []
    out: list[Path] = []
    for part in raw.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.append(Path(p).expanduser().resolve())
        except OSError as e:
            _log.warning("skip bad SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS entry %r: %s", p, e)
    return out


def _path_under_allowed_root(path: Path, roots: list[Path]) -> bool:
    try:
        pr = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            pr.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _rel_key_under_root(abs_file: Path, root: Path) -> str | None:
    try:
        return abs_file.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _collect_walk_paths(root: Path, path_prefix: str | None, max_files: int) -> list[str]:
    prefix = (path_prefix or "").strip().replace("\\", "/")
    if prefix.endswith("/"):
        prefix = prefix[:-1]
    prefix_slash = f"{prefix}/" if prefix else ""

    out: list[str] = []
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        base = Path(dirpath)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for fn in filenames:
            if len(out) >= max_files:
                return out
            full = (base / fn).resolve()
            if not full.is_file():
                continue
            try:
                rel = full.relative_to(root).as_posix()
            except ValueError:
                continue
            if prefix:
                if not (rel == prefix or rel.startswith(prefix_slash)):
                    continue
            stem = full.suffix.lower()
            if stem not in EXT_TO_LANG:
                continue
            out.append(rel)
    out.sort()
    return out[:max_files]


def apply_local_code_scan(
    root: str,
    project_id: int = 0,
    paths: list[str] | None = None,
    path_prefix: str | None = None,
) -> dict[str, Any]:
    """
    Quét thư mục local đã được phép, ghi :Commit (source=local_scan) + :CodeFile + ES như ingest GitHub.

    `root`: đường dẫn tuyệt đối hoặc tương đối; phải nằm trong một entry của SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS.
    `project_id`: >0 hoặc 0 khi dùng SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID.
    `paths`: danh sách đường dẫn tương đối trong `root` (POSIX); None/[] = walk cây.
    """
    allowed = _parse_allowed_roots()
    if not allowed:
        return {
            "ok": False,
            "error": "local_scan_disabled",
            "hint": "set SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS to comma-separated absolute paths",
        }

    pid = int(project_id) if int(project_id) > 0 else 0
    if pid <= 0:
        fb = (os.environ.get("SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID") or "").strip()
        if fb:
            try:
                pid = int(fb)
            except ValueError:
                pid = 0
    if pid <= 0:
        return {
            "ok": False,
            "error": "project_id_required",
            "hint": "pass project_id > 0 or set SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID",
        }

    try:
        root_path = Path(root).expanduser().resolve()
    except OSError as e:
        return {"ok": False, "error": "bad_root", "detail": str(e)}

    if not root_path.is_dir():
        return {"ok": False, "error": "root_not_a_directory", "root": str(root_path)}

    if not _path_under_allowed_root(root_path, allowed):
        return {
            "ok": False,
            "error": "root_not_allowed",
            "root": str(root_path),
            "hint": "add this directory to SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS",
        }

    max_files = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILES") or "50").strip() or "50")
    max_bytes = int((os.environ.get("SECOND_BRAIN_GITHUB_MAX_FILE_BYTES") or "400000").strip() or "400000")

    explicit = paths is not None and len(paths) > 0
    if explicit:
        touched: list[str] = []
        for p in paths:
            rel = (p or "").strip().replace("\\", "/").lstrip("/")
            if not rel or ".." in rel.split("/"):
                return {"ok": False, "error": "bad_path_entry", "path": p}
            abs_f = (root_path / rel).resolve()
            if not _path_under_allowed_root(abs_f, allowed):
                return {"ok": False, "error": "path_escapes_allowed_roots", "path": rel}
            try:
                abs_f.relative_to(root_path.resolve())
            except ValueError:
                return {"ok": False, "error": "path_outside_root", "path": rel}
            if not abs_f.is_file():
                continue
            if abs_f.suffix.lower() not in EXT_TO_LANG:
                continue
            touched.append(rel)
        touched = list(dict.fromkeys(touched))[:max_files]
    else:
        touched = _collect_walk_paths(root_path, path_prefix, max_files)

    from second_brain.neo4j_store import node_ref, node_ref_slug, run_write

    h = hashlib.sha256(str(root_path).encode("utf-8", errors="replace")).hexdigest()[:24]
    pseudo_sha = f"local{h}"[:40]
    cref = node_ref_slug(pid, "commit", pseudo_sha[:40])
    pref = node_ref(pid, "project", pid)
    ts = _now()
    display_root = str(root_path)[:512]
    msg = f"local scan {display_root}"

    repo_key = normalize_local_repo_key(str(root_path))
    full_name = f"local:{display_root}"

    gref = merge_git_repository(
        project_id=pid,
        pref=pref,
        repo_key=repo_key,
        repo_full_name=full_name,
        source="local_scan",
        ts=ts,
        run_write_fn=run_write,
    )

    run_write(
        """
        MERGE (c:Commit {ref: $cref})
        SET c.project_id = $project_id, c.sha = $sha, c.message = $msg,
            c.repo_key = $repo_key, c.repo_full_name = $repo_fn, c.ingested_at = $ts, c.source = 'local_scan'
        MERGE (p:Project {ref: $pref})-[:HAS_COMMIT]->(c)
        """,
        {
            "pref": pref,
            "project_id": pid,
            "cref": cref,
            "sha": pseudo_sha[:64],
            "msg": msg[:8000],
            "repo_key": repo_key[:256],
            "repo_fn": full_name[:512],
            "ts": ts,
        },
    )
    link_commit_to_repository(project_id=pid, cref=cref, gref=gref, run_write_fn=run_write)

    def get_content(rel_path: str) -> str | None:
        abs_f = (root_path / rel_path).resolve()
        if not abs_f.is_file():
            return None
        if not _path_under_allowed_root(abs_f, allowed):
            return None
        rk = _rel_key_under_root(abs_f, root_path)
        if rk != rel_path:
            return None
        try:
            return abs_f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            _log.warning("read failed %s: %s", abs_f, e)
            return None

    from second_brain.ingest_github import _process_touched_code_paths

    sub = _process_touched_code_paths(
        project_id=pid,
        repo_key=repo_key,
        gref=gref,
        cref=cref,
        full_name=full_name,
        sha=pseudo_sha,
        removed=[],
        touched=touched,
        commit_message_line=msg.split("\n", 1)[0].strip(),
        ts=ts,
        es_event_type="local.code_scan",
        max_files=max_files,
        max_bytes=max_bytes,
        get_content=get_content,
        file_changes={},
        fetch_diff=False,
        diff_max_patch=0,
        diff_max_files=0,
        diff_scope="touched",
    )

    return {
        "ok": True,
        "project_id": pid,
        "root": display_root,
        "pseudo_commit_sha": pseudo_sha,
        "repo_key": repo_key,
        "git_repository_ref": gref,
        "paths_mode": "explicit" if explicit else "walk",
        "paths_touched": len(touched),
        "stats": {"commits": 1, **sub},
    }
