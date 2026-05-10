"""Map Agile Studio fan-out payloads into Neo4j + Elasticsearch."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from second_brain.es_store import delete_by_ref, index_chunk
from second_brain.neo4j_store import node_ref, node_ref_slug, run_write


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iw(project_id: int, summary: str, event_type: str, data: dict[str, Any]) -> str:
    """Text for embedding."""
    parts = [summary, event_type, json.dumps(data, ensure_ascii=False, default=str)]
    return "\n".join(parts)


def _body_preview(data: dict[str, Any], *, max_len: int = 8000) -> str:
    """Nội dung comment/wiki để đưa vào ES (payload có thể có body_preview hoặc content_preview)."""
    for key in ("body_preview", "content_preview", "content", "body"):
        raw = data.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:max_len]
    return ""


def apply_agile_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Process ingest body from Hub (event_type, project_id, summary, data, …)."""
    et = str(payload.get("event_type") or "").strip()
    summary = str(payload.get("summary") or "")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_pid = data.get("project_id", payload.get("project_id"))
    try:
        project_id = int(raw_pid)
    except (TypeError, ValueError):
        return {"ok": False, "error": "missing_or_invalid_project_id", "event_type": et}

    ts = _now()

    def _idx(
        *,
        ref: str,
        label: str,
        text: str,
        event_type: str,
        scope: str = "project",
        visibility: str = "project",
        status: str = "",
        tags: list[str] | None = None,
    ) -> None:
        index_chunk(
            project_id=project_id,
            ref=ref,
            label=label,
            text=text,
            event_type=event_type,
            scope=scope,
            visibility=visibility,
            status=status,
            tags=tags,
        )

    if et == "agile_studio.project.created":
        pid = project_id
        name = str(payload.get("project_name") or data.get("name") or f"project-{pid}")
        pref = node_ref(pid, "project", pid)
        run_write(
            """
            MERGE (p:Project {ref: $ref})
            SET p.project_id = $project_id, p.name = $name, p.ingested_at = $ts
            """,
            {"ref": pref, "project_id": pid, "name": name, "ts": ts},
        )
        _idx(ref=pref, label="Project", text=_iw(pid, summary, et, data), event_type=et)
        return {"ok": True, "event_type": et, "ref": pref}

    if et in ("agile_studio.story.created", "agile_studio.story.updated"):
        sid = int(data.get("story_id") or 0)
        if sid <= 0:
            return {"ok": False, "error": "missing_story_id", "event_type": et}
        title = str(data.get("title") or "")
        status = str(data.get("status") or "")
        sk = str(data.get("story_key") or "")
        sref = node_ref(project_id, "story", sid)
        pref = node_ref(project_id, "project", project_id)
        run_write(
            """
            MERGE (p:Project {ref: $pref})
            SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
            MERGE (s:Story {ref: $sref})
            SET s.project_id = $project_id, s.agile_id = $sid, s.title = $title, s.status = $status,
                s.story_key = $story_key, s.ingested_at = $ts
            MERGE (p)-[:HAS_STORY]->(s)
            """,
            {
                "pref": pref,
                "project_id": project_id,
                "sref": sref,
                "sid": sid,
                "title": title,
                "status": status,
                "story_key": sk,
                "ts": ts,
            },
        )
        _idx(
            ref=sref,
            label="Story",
            text=_iw(project_id, summary, et, data) + f"\n{title}",
            event_type=et,
            status=status[:64] if status else "",
        )
        return {"ok": True, "event_type": et, "ref": sref}

    if et in ("agile_studio.comment.created", "agile_studio.comment.updated"):
        cid = int(data.get("comment_id") or 0)
        sid = int(data.get("story_id") or 0)
        if cid <= 0 or sid <= 0:
            return {"ok": False, "error": "missing_comment_or_story", "event_type": et}
        cref = node_ref(project_id, "comment", cid)
        sref = node_ref(project_id, "story", sid)
        mid = int(data.get("author_member_id") or 0)
        mref = node_ref(project_id, "member", mid) if mid > 0 else None
        preview = _body_preview(data)
        run_write(
            """
            MERGE (s:Story {ref: $sref})
            SET s.project_id = $project_id, s.ingested_at = coalesce(s.ingested_at, $ts)
            MERGE (c:Comment {ref: $cref})
            SET c.project_id = $project_id, c.agile_id = $cid, c.kind = 'story_comment',
                c.body_preview = $preview, c.ingested_at = $ts
            MERGE (c)-[:ON]->(s)
            """,
            {"sref": sref, "cref": cref, "project_id": project_id, "cid": cid, "ts": ts, "preview": preview[:8000]},
        )
        if mref:
            run_write(
                """
                MERGE (m:Member {ref: $mref})
                SET m.project_id = $project_id, m.agile_id = $mid, m.ingested_at = $ts
                MERGE (c:Comment {ref: $cref})
                MERGE (m)-[:AUTHORED]->(c)
                """,
                {"mref": mref, "project_id": project_id, "mid": mid, "cref": cref, "ts": ts},
            )
        blob = _iw(project_id, summary, et, data)
        if preview:
            blob = f"{blob}\n---\n{preview}"
        _idx(ref=cref, label="Comment", text=blob, event_type=et)
        return {"ok": True, "event_type": et, "ref": cref}

    if et == "agile_studio.comment.deleted":
        cid = int(data.get("comment_id") or 0)
        if cid <= 0:
            return {"ok": False, "error": "missing_comment_id", "event_type": et}
        cref = node_ref(project_id, "comment", cid)
        run_write(
            "MATCH (c:Comment {ref: $cref}) DETACH DELETE c",
            {"cref": cref},
        )
        delete_by_ref(cref)
        return {"ok": True, "event_type": et, "deleted": cref}

    if et in ("agile_studio.task_comment.created", "agile_studio.task_comment.updated"):
        cid = int(data.get("comment_id") or 0)
        tid = int(data.get("task_id") or 0)
        if cid <= 0 or tid <= 0:
            return {"ok": False, "error": "missing_task_comment_ids", "event_type": et}
        cref = node_ref(project_id, "comment", cid)
        tref = node_ref(project_id, "task", tid)
        mid = int(data.get("author_member_id") or 0)
        preview = _body_preview(data)
        run_write(
            """
            MERGE (t:Task {ref: $tref})
            SET t.project_id = $project_id, t.agile_id = $tid, t.ingested_at = coalesce(t.ingested_at, $ts)
            MERGE (c:Comment {ref: $cref})
            SET c.project_id = $project_id, c.agile_id = $cid, c.kind = 'task_comment',
                c.body_preview = $preview, c.ingested_at = $ts
            MERGE (c)-[:ON]->(t)
            """,
            {"tref": tref, "cref": cref, "project_id": project_id, "tid": tid, "cid": cid, "ts": ts, "preview": preview[:8000]},
        )
        if mid > 0:
            mref = node_ref(project_id, "member", mid)
            run_write(
                """
                MERGE (m:Member {ref: $mref})
                SET m.project_id = $project_id, m.agile_id = $mid, m.ingested_at = $ts
                MERGE (c:Comment {ref: $cref})
                MERGE (m)-[:AUTHORED]->(c)
                """,
                {"mref": mref, "project_id": project_id, "mid": mid, "cref": cref, "ts": ts},
            )
        story_ids_raw = data.get("story_ids")
        if isinstance(story_ids_raw, list):
            for sid in story_ids_raw:
                try:
                    story_i = int(sid)
                except (TypeError, ValueError):
                    continue
                if story_i <= 0:
                    continue
                sref = node_ref(project_id, "story", story_i)
                run_write(
                    """
                    MATCH (s:Story {ref: $sref}), (t:Task {ref: $tref})
                    WHERE s.project_id = $project_id AND t.project_id = $project_id
                    MERGE (s)-[:HAS_TASK]->(t)
                    """,
                    {"sref": sref, "tref": tref, "project_id": project_id},
                )
        blob = _iw(project_id, summary, et, data)
        if preview:
            blob = f"{blob}\n---\n{preview}"
        _idx(ref=cref, label="TaskComment", text=blob, event_type=et)
        return {"ok": True, "event_type": et, "ref": cref}

    if et == "agile_studio.task_comment.deleted":
        cid = int(data.get("comment_id") or 0)
        if cid <= 0:
            return {"ok": False, "error": "missing_comment_id", "event_type": et}
        cref = node_ref(project_id, "comment", cid)
        run_write("MATCH (c:Comment {ref: $cref}) DETACH DELETE c", {"cref": cref})
        delete_by_ref(cref)
        return {"ok": True, "event_type": et, "deleted": cref}

    # Wiki document (Hub fan-out agile_studio.wiki_document.*)
    if et in ("agile_studio.wiki_document.created", "agile_studio.wiki_document.updated"):
        wid = str(data.get("wiki_document_id") or "").strip()
        if not wid:
            return {"ok": False, "error": "missing_wiki_document_id", "event_type": et}
        title = str(data.get("title") or "")
        slug = str(data.get("slug") or "")
        preview = _body_preview(data, max_len=16000)
        tags_raw = data.get("tags")
        tag_list: list[str] = []
        if isinstance(tags_raw, list):
            tag_list = [str(t).strip() for t in tags_raw if str(t).strip()][:50]
        dref = node_ref_slug(project_id, "document", wid)
        pref = node_ref(project_id, "project", project_id)
        run_write(
            """
            MERGE (p:Project {ref: $pref})
            SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
            MERGE (d:Document {ref: $dref})
            SET d.project_id = $project_id, d.wiki_id = $wid, d.title = $title, d.slug = $slug,
                d.body_preview = $preview, d.tags = $tags, d.ingested_at = $ts
            MERGE (p)-[:HAS_DOCUMENT]->(d)
            """,
            {
                "pref": pref,
                "project_id": project_id,
                "dref": dref,
                "wid": wid,
                "title": title[:2000],
                "slug": slug[:256],
                "preview": preview[:16000],
                "tags": tag_list,
                "ts": ts,
            },
        )
        blob = "\n".join([summary, et, title, slug, preview or json.dumps(data, ensure_ascii=False, default=str)])
        _idx(ref=dref, label="WikiDocument", text=blob, event_type=et, tags=tag_list)
        return {"ok": True, "event_type": et, "ref": dref}

    if et == "agile_studio.wiki_document.deleted":
        wid = str(data.get("wiki_document_id") or "").strip()
        if not wid:
            return {"ok": False, "error": "missing_wiki_document_id", "event_type": et}
        dref = node_ref_slug(project_id, "document", wid)
        run_write("MATCH (d:Document {ref: $dref}) DETACH DELETE d", {"dref": dref})
        delete_by_ref(dref)
        return {"ok": True, "event_type": et, "deleted": dref}

    # Wiki comment (event_type legacy wiki_comment_* từ Hub)
    if et in ("wiki_comment_created", "wiki_comment_updated", "agile_studio.wiki_comment.created", "agile_studio.wiki_comment.updated"):
        wcid = str(data.get("wiki_comment_id") or "").strip()
        wid = str(data.get("wiki_document_id") or "").strip()
        if not wcid or not wid:
            return {"ok": False, "error": "missing_wiki_comment_or_doc", "event_type": et}
        preview = _body_preview(data, max_len=12000)
        quote_prev = str(data.get("quote_preview") or "")[:4000]
        excerpt = str(data.get("quoted_excerpt_preview") or "")[:4000]
        dref = node_ref_slug(project_id, "document", wid)
        wcref = node_ref_slug(project_id, "wikicomment", wcid)
        mid = int(data.get("author_member_id") or 0)
        mref = node_ref(project_id, "member", mid) if mid > 0 else None
        pref = node_ref(project_id, "project", project_id)
        doc_title = str(data.get("doc_title") or "")
        doc_slug = str(data.get("doc_slug") or "")
        run_write(
            """
            MERGE (p:Project {ref: $pref})
            SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
            MERGE (d:Document {ref: $dref})
            SET d.project_id = $project_id, d.wiki_id = $wid, d.title = coalesce($doc_title, d.title),
                d.slug = coalesce($doc_slug, d.slug), d.ingested_at = coalesce(d.ingested_at, $ts)
            MERGE (w:WikiComment {ref: $wcref})
            SET w.project_id = $project_id, w.wiki_comment_id = $wcid, w.body_preview = $preview,
                w.ingested_at = $ts
            MERGE (w)-[:ON]->(d)
            MERGE (p)-[:HAS_DOCUMENT]->(d)
            """,
            {
                "pref": pref,
                "project_id": project_id,
                "dref": dref,
                "wid": wid,
                "wcref": wcref,
                "wcid": wcid,
                "preview": preview[:12000],
                "doc_title": doc_title[:2000],
                "doc_slug": doc_slug[:256],
                "ts": ts,
            },
        )
        if mref:
            run_write(
                """
                MERGE (m:Member {ref: $mref})
                SET m.project_id = $project_id, m.agile_id = $mid, m.ingested_at = $ts
                MERGE (w:WikiComment {ref: $wcref})
                MERGE (m)-[:AUTHORED]->(w)
                """,
                {"mref": mref, "project_id": project_id, "mid": mid, "wcref": wcref, "ts": ts},
            )
        blob_parts = [summary, et, doc_title, preview]
        if quote_prev:
            blob_parts.append(f"quote: {quote_prev}")
        if excerpt:
            blob_parts.append(f"quoted_excerpt: {excerpt}")
        blob = "\n".join(blob_parts)
        _idx(ref=wcref, label="WikiComment", text=blob, event_type=et)
        return {"ok": True, "event_type": et, "ref": wcref}

    if et in ("wiki_comment_deleted", "agile_studio.wiki_comment.deleted"):
        wcid = str(data.get("wiki_comment_id") or "").strip()
        if not wcid:
            return {"ok": False, "error": "missing_wiki_comment_id", "event_type": et}
        wcref = node_ref_slug(project_id, "wikicomment", wcid)
        run_write("MATCH (w:WikiComment {ref: $wcref}) DETACH DELETE w", {"wcref": wcref})
        delete_by_ref(wcref)
        return {"ok": True, "event_type": et, "deleted": wcref}

    # Git commit (stub / tích hợp CI — payload tùy biến)
    if et in ("second_brain.git.commit", "agile_studio.git.commit"):
        sha = str(data.get("sha") or data.get("commit_sha") or "").strip()
        if len(sha) < 7:
            return {"ok": False, "error": "missing_commit_sha", "event_type": et}
        msg = str(data.get("message") or data.get("commit_message") or "")[:8000]
        repo = str(data.get("repo") or data.get("repository") or "")[:512]
        cref = node_ref_slug(project_id, "commit", sha[:40])
        pref = node_ref(project_id, "project", project_id)
        run_write(
            """
            MERGE (p:Project {ref: $pref})
            SET p.project_id = $project_id, p.ingested_at = coalesce(p.ingested_at, $ts)
            MERGE (c:Commit {ref: $cref})
            SET c.project_id = $project_id, c.sha = $sha, c.message = $msg, c.repo = $repo, c.ingested_at = $ts
            MERGE (p)-[:HAS_COMMIT]->(c)
            """,
            {
                "pref": pref,
                "project_id": project_id,
                "cref": cref,
                "sha": sha[:64],
                "msg": msg,
                "repo": repo,
                "ts": ts,
            },
        )
        _idx(ref=cref, label="Commit", text=f"{repo}\n{sha}\n{msg}\n{summary}", event_type=et)
        return {"ok": True, "event_type": et, "ref": cref}

    return {"ok": True, "skipped": True, "event_type": et}
