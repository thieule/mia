"""Trích id task/story từ commit message (GitHub ingest + stub git từ Hub)."""

from __future__ import annotations

import os
import re
from typing import Any

from second_brain.refs import node_ref


def parse_task_ids(message: str) -> list[int]:
    pat = (os.environ.get("SECOND_BRAIN_COMMIT_TASK_PATTERN") or "").strip()
    if not pat:
        pat = r"(?:task|ticket|tid)\s*[#:_-]?\s*(\d+)"
    found = re.findall(pat, message, flags=re.IGNORECASE)
    out: list[int] = []
    for x in found:
        try:
            out.append(int(x))
        except ValueError:
            continue
    return sorted(set(out))


def _story_ids_from_slug_key(message: str) -> list[int]:
    """Ví dụ Agile slug-story_number: `mia-12` khi SECOND_BRAIN_COMMIT_STORY_SLUG=mia."""
    slug = (os.environ.get("SECOND_BRAIN_COMMIT_STORY_SLUG") or "").strip()
    if not slug:
        return []
    try:
        pat = rf"\b{re.escape(slug)}-(\d+)\b"
        return [int(x) for x in re.findall(pat, message, flags=re.IGNORECASE)]
    except re.error:
        return []


def parse_story_ids(message: str) -> list[int]:
    pat = (os.environ.get("SECOND_BRAIN_COMMIT_STORY_PATTERN") or "").strip()
    if not pat:
        pat = r"(?:story|st)\s*[#:_-]?\s*(\d+)"
    found = re.findall(pat, message, flags=re.IGNORECASE)
    extra_pat = (os.environ.get("SECOND_BRAIN_COMMIT_FIXES_PATTERN") or "").strip()
    if extra_pat:
        try:
            found.extend(re.findall(extra_pat, message, flags=re.IGNORECASE))
        except re.error:
            pass
    out: list[int] = []
    for x in found:
        try:
            out.append(int(x))
        except ValueError:
            continue
    out.extend(_story_ids_from_slug_key(message))
    return sorted(set(out))


def link_commit_tasks_and_stories(
    *,
    project_id: int,
    pref: str,
    cref: str,
    message: str,
    ts: str,
    run_write_fn: Any,
) -> None:
    """Neo4j: Task/Story ↔ Commit (dùng chung ingest_github và ingest_agile git stub)."""
    for tid in parse_task_ids(message):
        tref = node_ref(project_id, "task", tid)
        run_write_fn(
            """
            MATCH (t:Task {ref: $tref}), (c:Commit {ref: $cref})
            WHERE t.project_id = $project_id AND c.project_id = $project_id
            MERGE (t)-[:IMPLEMENTED_BY]->(c)
            """,
            {"tref": tref, "cref": cref, "project_id": project_id},
        )

    for sid in parse_story_ids(message):
        sref = node_ref(project_id, "story", sid)
        run_write_fn(
            """
            MATCH (c:Commit {ref: $cref}) WHERE c.project_id = $project_id
            MATCH (p:Project {ref: $pref}) WHERE p.project_id = $project_id
            MERGE (s:Story {ref: $sref})
            SET s.project_id = $project_id, s.agile_id = $sid,
                s.ingested_at = coalesce(s.ingested_at, $ts)
            MERGE (p)-[:HAS_STORY]->(s)
            MERGE (c)-[:IMPLEMENTS]->(s)
            """,
            {
                "cref": cref,
                "pref": pref,
                "sref": sref,
                "project_id": project_id,
                "sid": sid,
                "ts": ts,
            },
        )
