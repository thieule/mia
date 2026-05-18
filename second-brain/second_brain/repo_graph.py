"""Neo4j: Project ↔ GitRepository ↔ CodeFile / Commit (multi-repo per Agile project)."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable

from second_brain.refs import node_ref_slug

WriteFn = Callable[..., None]


def normalize_github_repo_key(full_name: str) -> str:
    """Khóa ổn định cho repo GitHub: owner/repo (chữ thường)."""
    key = (full_name or "").strip().lower()
    if "/" not in key:
        return re.sub(r"[^a-z0-9._/-]", "_", key)[:128] or "unknown"
    return key[:256]


def normalize_local_repo_key(root_path: str) -> str:
    """Khóa repo cho workspace local (một root = một logical repo)."""
    norm = str(root_path).strip()
    digest = hashlib.sha256(norm.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"local:{digest}"


def git_repository_ref(project_id: int, repo_key: str) -> str:
    return node_ref_slug(project_id, "gitrepository", repo_key)


def codefile_ref(project_id: int, repo_key: str, path: str) -> str:
    """ref CodeFile tách theo repo — tránh trùng path giữa nhiều repo cùng project."""
    return node_ref_slug(project_id, "codefile", f"{repo_key}::{path}")


def codefunction_ref(project_id: int, repo_key: str, path: str, qualname: str) -> str:
    return node_ref_slug(project_id, "codefunction", f"{repo_key}::{path}::{qualname}")


def merge_git_repository(
    *,
    project_id: int,
    pref: str,
    repo_key: str,
    repo_full_name: str,
    source: str,
    ts: str,
    run_write_fn: WriteFn,
) -> str:
    """
    MERGE Project, GitRepository và (Project)-[:HAS_REPOSITORY]->(GitRepository).
    Trả về ref của GitRepository.
    """
    gref = git_repository_ref(project_id, repo_key)
    run_write_fn(
        """
        MERGE (p:Project {ref: $pref})
        SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
        MERGE (g:GitRepository {ref: $gref})
        SET g.project_id = $project_id, g.repo_key = $repo_key, g.full_name = $repo_full_name,
            g.source = $source, g.ingested_at = $ts
        MERGE (p)-[:HAS_REPOSITORY]->(g)
        """,
        {
            "pref": pref,
            "project_id": project_id,
            "gref": gref,
            "repo_key": repo_key[:256],
            "repo_full_name": repo_full_name[:512],
            "source": (source or "unknown")[:32],
            "ts": ts,
        },
    )
    return gref


def link_commit_to_repository(
    *,
    project_id: int,
    cref: str,
    gref: str,
    run_write_fn: WriteFn,
) -> None:
    run_write_fn(
        """
        MATCH (c:Commit {ref: $cref}), (g:GitRepository {ref: $gref})
        WHERE c.project_id = $project_id AND g.project_id = $project_id
        MERGE (c)-[:IN_REPOSITORY]->(g)
        """,
        {"cref": cref, "gref": gref, "project_id": project_id},
    )


def link_codefile_to_repository(
    *,
    project_id: int,
    gref: str,
    fref: str,
    run_write_fn: WriteFn,
) -> None:
    run_write_fn(
        """
        MATCH (g:GitRepository {ref: $gref}), (f:CodeFile {ref: $fref})
        WHERE g.project_id = $project_id AND f.project_id = $project_id
        MERGE (g)-[:HAS_CODE_FILE]->(f)
        """,
        {"gref": gref, "fref": fref, "project_id": project_id},
    )
