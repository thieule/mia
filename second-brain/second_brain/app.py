from __future__ import annotations

import hmac
import hashlib
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    p = _ROOT / ".env"
    if not p.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(p, override=False)


_load_dotenv()

_log = logging.getLogger(__name__)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit("pip install mcp") from e

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from second_brain.adr_extract import propose_adr_json
from second_brain.cypher_guard import assert_read_only_cypher
from second_brain.ingest_agile import apply_agile_event
from second_brain.ingest_github import (
    apply_github_code_refresh,
    apply_github_compare,
    apply_github_push,
    verify_github_signature,
)
from second_brain.ingest_local import apply_local_code_scan
from second_brain import es_store
from second_brain.lesson_extract import propose_lesson_json
from second_brain.neo4j_store import close_driver, ensure_constraints, neo4j_driver, node_ref, run_read, run_write

_MCP_HOST = os.environ.get("MCP_HOST", os.environ.get("FASTMCP_HOST", "127.0.0.1"))
_MCP_PORT = int(os.environ.get("MCP_PORT", os.environ.get("FASTMCP_PORT", "8000")))
_MCP_HTTP_PATH = (os.environ.get("MCP_HTTP_PATH") or "/mcp").strip() or "/mcp"


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


_MCP_STATELESS = _env_bool("MCP_STATELESS_HTTP", True)
_MCP_JSON_RESPONSE = _env_bool("MCP_JSON_RESPONSE", True)

ALLOWED_REL_TYPES = frozenset(
    {
        "RELATES_TO",
        "DEPENDS_ON",
        "REFERENCES",
        "AUTHORED",
        "ON",
        "HAS_TASK",
        "HAS_STORY",
        "HAS_DOCUMENT",
        "HAS_COMMIT",
        "HAS_REPOSITORY",
        "HAS_CODE_FILE",
        "IN_REPOSITORY",
        "IMPLEMENTS",
        "DECIDED_IN",
        "SUPERSEDES",
        "DERIVED_FROM",
        "PROVIDES_FEEDBACK",
        "MODIFIES",
        "IMPLEMENTED_BY",
        "DEFINES",
        "CALLS",
        "CONTAINS",
        "MEMBER_OF",
    }
)

mcp = FastMCP(
    "second_brain",
    host=_MCP_HOST.strip() or "127.0.0.1",
    port=_MCP_PORT,
    instructions="Second Brain: Neo4j knowledge graph + Elasticsearch (vector / hybrid). "
    "HTTP: /ingest/agile-event, /ingest/github-webhook (push), /ingest/github-compare (diff two refs), "
    "/ingest/local-code-scan (filesystem under SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS). "
    "Tools: brain_query_graph, brain_get_neighborhood, brain_upsert_relation, brain_search_knowledge "
    "(mode vector|hybrid), brain_github_compare (GitHub API compare, read-only), "
    "brain_refresh_github_code (sync repo/branch/commit into graph+ES), brain_scan_local_code, "
    "brain_remember_decision, brain_remember_lesson, brain_extract_lesson_from_text, "
    "brain_extract_adr_from_text, brain_feedback_create, brain_supersede_decision. "
    "Set NEO4J_*, ELASTICSEARCH_URL, GEMINI_API_KEY. Optional SECOND_BRAIN_MCP_SECRET (Bearer / X-Second-Brain-MCP-Secret).",
    streamable_http_path=_MCP_HTTP_PATH,
    stateless_http=_MCP_STATELESS,
    json_response=_MCP_JSON_RESPONSE,
)


def _boot_schema() -> None:
    driver = neo4j_driver()
    ensure_constraints(driver)
    es_store.ensure_index(es_store.es_client())


@mcp.custom_route("/health", methods=["GET"])
async def _health(_request: Request) -> JSONResponse:
    neo_ok = False
    es_ok = False
    try:
        neo4j_driver().verify_connectivity()
        neo_ok = True
    except Exception as e:  # pragma: no cover
        _log.debug("neo4j health: %s", e)
    try:
        es_store.es_client().info()
        es_ok = True
    except Exception as e:  # pragma: no cover
        _log.debug("es health: %s", e)
    return JSONResponse(
        {
            "ok": neo_ok and es_ok,
            "service": "second-brain-mcp",
            "neo4j": neo_ok,
            "elasticsearch": es_ok,
            "streamable_http_path": _MCP_HTTP_PATH,
        }
    )


def _ingest_secret_ok(request: Request) -> bool:
    expected = (os.environ.get("SECOND_BRAIN_INGEST_SECRET") or "").strip()
    if not expected:
        return False
    got = (request.headers.get("x-second-brain-secret") or "").strip()
    return got == expected


@mcp.custom_route("/ingest/agile-event", methods=["POST"])
async def _ingest_agile(request: Request) -> JSONResponse:
    if not _ingest_secret_ok(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    try:
        out = apply_agile_event(body)
        return JSONResponse(out)
    except Exception as e:
        _log.exception("ingest failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


def _github_webhook_secret_ok(body: bytes, request: Request) -> bool:
    secret = (os.environ.get("SECOND_BRAIN_GITHUB_WEBHOOK_SECRET") or "").strip()
    if not secret:
        return False
    sig = request.headers.get("x-hub-signature-256")
    return verify_github_signature(body, sig, secret)


@mcp.custom_route("/ingest/github-webhook", methods=["POST"])
async def _ingest_github_webhook(request: Request) -> JSONResponse:
    body = await request.body()
    ev = (request.headers.get("x-github-event") or "").strip()
    if ev == "ping":
        return JSONResponse({"ok": True, "ping": True})
    if ev != "push":
        return JSONResponse({"ok": True, "skipped": True, "event": ev})
    if not _github_webhook_secret_ok(body, request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(payload, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    try:
        out = apply_github_push(payload)
        return JSONResponse(out)
    except Exception as e:
        _log.exception("github ingest failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@mcp.custom_route("/ingest/github-compare", methods=["POST"])
async def _ingest_github_compare(request: Request) -> JSONResponse:
    """So sánh hai ref (giống MCP `brain_github_compare`), bảo vệ bằng X-Second-Brain-Secret."""
    if not _ingest_secret_ok(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    repo = str(body.get("repository") or "").strip()
    base = str(body.get("base") or "").strip()
    head = str(body.get("head") or "").strip()
    if not repo or not base or not head:
        return JSONResponse({"ok": False, "error": "repository_base_head_required"}, status_code=400)
    try:
        out = apply_github_compare(repo, base, head)
        code = 200 if out.get("ok") else 400
        return JSONResponse(out, status_code=code)
    except Exception as e:
        _log.exception("github compare failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@mcp.tool()
def brain_github_compare(repository: str, base: str, head: str) -> str:
    """So sánh hai ref GitHub (`base`...`head`, branch hoặc SHA). Cần SECOND_BRAIN_GITHUB_TOKEN; không ghi Neo4j/ES."""
    out = apply_github_compare(
        (repository or "").strip(),
        (base or "").strip(),
        (head or "").strip(),
    )
    return json.dumps(out, ensure_ascii=False, default=str)


@mcp.tool()
def brain_refresh_github_code(
    repository: str,
    ref: str,
    project_id: int = 0,
    paths_json: str = "[]",
    path_prefix: str = "",
) -> str:
    """Đồng bộ code GitHub vào Neo4j + Elasticsearch (Agent chủ động gọi, không cần webhook).

    repository: dạng owner/repo. ref: tên nhánh hoặc SHA commit (GitHub API).
    project_id: 0 → dùng SECOND_BRAIN_GITHUB_REPO_PROJECT_MAP hoặc SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID.
    paths_json: JSON array đường dẫn file trong repo; [] = quét cây Git các file có đuôi đã hỗ trợ (giới hạn SECOND_BRAIN_GITHUB_MAX_FILES).
    path_prefix: khi quét cây, chỉ lấy path bắt đầu bằng prefix này (vd second_brain/).
    Cần SECOND_BRAIN_GITHUB_TOKEN; tuân env max file/size như webhook.
    """
    try:
        raw_paths = json.loads(paths_json or "[]")
        if not isinstance(raw_paths, list):
            raise ValueError("paths_json phải là JSON array")
        paths_list = [str(x).strip() for x in raw_paths if str(x).strip()]
    except json.JSONDecodeError as e:
        raise ValueError(f"paths_json không hợp lệ: {e}") from e

    paths_arg: list[str] | None = paths_list if paths_list else None
    prefix_arg = (path_prefix or "").strip() or None

    out = apply_github_code_refresh(
        repository,
        ref.strip(),
        project_id=int(project_id),
        paths=paths_arg,
        path_prefix=prefix_arg,
    )
    return json.dumps(out, ensure_ascii=False, default=str)


@mcp.tool()
def brain_scan_local_code(
    root: str,
    project_id: int = 0,
    paths_json: str = "[]",
    path_prefix: str = "",
) -> str:
    """Quét code trên disk (cùng process Second Brain) vào Neo4j + ES.

    Bắt buộc cấu hình SECOND_BRAIN_LOCAL_CODE_SCAN_ROOTS (comma-separated): chỉ index khi `root`
    nằm trong một trong các gốc đó (an toàn). `project_id` > 0 hoặc dùng SECOND_BRAIN_GITHUB_DEFAULT_PROJECT_ID.
    paths_json: JSON array đường dẫn tương đối trong root; [] = walk (đuôi giống ingest GitHub, giới hạn SECOND_BRAIN_GITHUB_MAX_FILES).
    path_prefix: khi walk, chỉ file có path bắt đầu bằng prefix này (vd second_brain/).
    """
    try:
        raw_paths = json.loads(paths_json or "[]")
        if not isinstance(raw_paths, list):
            raise ValueError("paths_json phải là JSON array")
        paths_list = [str(x).strip() for x in raw_paths if str(x).strip()]
    except json.JSONDecodeError as e:
        raise ValueError(f"paths_json không hợp lệ: {e}") from e

    paths_arg: list[str] | None = paths_list if paths_list else None
    prefix_arg = (path_prefix or "").strip() or None

    out = apply_local_code_scan(
        (root or "").strip(),
        project_id=int(project_id),
        paths=paths_arg,
        path_prefix=prefix_arg,
    )
    return json.dumps(out, ensure_ascii=False, default=str)


@mcp.custom_route("/ingest/local-code-scan", methods=["POST"])
async def _ingest_local_code_scan(request: Request) -> JSONResponse:
    """JSON { \"root\", \"project_id\"?, \"paths\"?, \"path_prefix\"? } + X-Second-Brain-Secret."""
    if not _ingest_secret_ok(request):
        return JSONResponse({"ok": False, "error": "unauthorized"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "invalid_json"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "expected_object"}, status_code=400)
    root = str(body.get("root") or "").strip()
    if not root:
        return JSONResponse({"ok": False, "error": "root_required"}, status_code=400)
    try:
        pid = int(body.get("project_id") or 0)
    except (TypeError, ValueError):
        return JSONResponse({"ok": False, "error": "bad_project_id"}, status_code=400)
    paths_raw = body.get("paths")
    paths_list: list[str] | None = None
    if isinstance(paths_raw, list) and paths_raw:
        paths_list = [str(x).strip() for x in paths_raw if str(x).strip()]
    prefix = str(body.get("path_prefix") or "").strip() or None
    try:
        out = apply_local_code_scan(root, project_id=pid, paths=paths_list, path_prefix=prefix)
        code = 200 if out.get("ok") else 400
        return JSONResponse(out, status_code=code)
    except Exception as e:
        _log.exception("local code scan failed")
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@mcp.tool()
def brain_query_graph(cypher_query: str, params_json: str = "{}") -> str:
    """Run read-only Cypher against Neo4j. params_json is a JSON object for query parameters."""
    assert_read_only_cypher(cypher_query)
    try:
        params = json.loads(params_json or "{}")
        if not isinstance(params, dict):
            raise ValueError("params_json must be a JSON object")
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid params_json: {e}") from e
    rows = run_read(cypher_query, params)
    return json.dumps({"rows": rows[:500], "truncated": len(rows) > 500}, ensure_ascii=False, default=str)


@mcp.tool()
def brain_get_neighborhood(node_ref: str, depth: int = 2) -> str:
    """Traverse outward from the node with property ref=$node_ref up to depth (max 3)."""
    ref = (node_ref or "").strip()
    if not ref:
        raise ValueError("node_ref required")
    d = max(1, min(int(depth), 3))
    cypher = f"""
    MATCH (n {{ref: $ref}})
    OPTIONAL MATCH (n)-[*1..{d}]-(m)
    RETURN collect(distinct n.ref) + collect(distinct m.ref) AS refs
    """.strip()
    rows = run_read(cypher, {"ref": ref})
    if not rows:
        return json.dumps({"root": ref, "depth": d, "related_refs": [], "note": "node_not_found"}, ensure_ascii=False)
    out = rows[0]
    # Dedupe while preserving order
    seen: set[str] = set()
    refs = []
    for r in out.get("refs") or []:
        if r is None or r in seen:
            continue
        sr = str(r).strip()
        if not sr:
            continue
        seen.add(sr)
        refs.append(sr)
    return json.dumps({"root": ref, "depth": d, "related_refs": refs[:200]}, ensure_ascii=False)


@mcp.tool()
def brain_upsert_relation(source_ref: str, target_ref: str, relationship_type: str, project_id: int = 0) -> str:
    """Create edge source-[type]->target if both nodes exist and share project_id when project_id>0."""
    st = (source_ref or "").strip()
    tt = (target_ref or "").strip()
    rt = (relationship_type or "").strip().upper()
    if not st or not tt:
        raise ValueError("source_ref and target_ref required")
    if rt not in ALLOWED_REL_TYPES:
        raise ValueError(f"relationship_type must be one of: {sorted(ALLOWED_REL_TYPES)}")
    pid = int(project_id)
    if pid > 0:
        cypher = f"""
        MATCH (a {{ref: $s}}), (b {{ref: $t}})
        WHERE a.project_id = $pid AND b.project_id = $pid
        MERGE (a)-[r:{rt}]->(b)
        """
        run_write(cypher, {"s": st, "t": tt, "pid": pid})
    else:
        cypher = f"MATCH (a {{ref: $s}}), (b {{ref: $t}}) MERGE (a)-[r:{rt}]->(b)"
        run_write(cypher, {"s": st, "t": tt})
    return json.dumps({"ok": True, "source": st, "target": tt, "relationship_type": rt}, ensure_ascii=False)


@mcp.tool()
def brain_search_knowledge(
    query: str,
    project_id: int = 0,
    top_k: int = 10,
    scope: str = "",
    visibility: str = "",
    search_mode: str = "vector",
    source_type: str = "",
) -> str:
    """Semantic search: search_mode \"vector\" (kNN) hoặc \"hybrid\" (kNN + BM25). source_type: \"\" hoặc agile|code|code_diff (patch GitHub đã ingest)."""
    q = (query or "").strip()
    if not q:
        raise ValueError("query required")
    pid = int(project_id)
    tk = max(1, min(int(top_k), 50))
    sc = (scope or "").strip() or None
    vis = (visibility or "").strip() or None
    st = (source_type or "").strip() or None
    mode = (search_mode or "vector").strip().lower()
    if pid <= 0:
        proj_filter = None
    else:
        proj_filter = pid
    if mode == "hybrid":
        hits = es_store.search_hybrid(
            query_text=q,
            project_id=proj_filter,
            top_k=tk,
            scope=sc,
            visibility=vis,
            source_type=st,
        )
    else:
        hits = es_store.search_knn(
            query_text=q,
            project_id=proj_filter,
            top_k=tk,
            scope=sc,
            visibility=vis,
            source_type=st,
        )
    return json.dumps({"hits": hits, "search_mode": mode}, ensure_ascii=False, default=str)


def _parse_tags_json(tags_json: str) -> list[str]:
    raw = (tags_json or "").strip()
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()][:50]
    except json.JSONDecodeError:
        pass
    return [t.strip() for t in raw.split(",") if t.strip()][:50]


@mcp.tool()
def brain_remember_decision(
    title: str,
    status: str,
    context: str,
    decision: str,
    consequences: str,
    project_id: int,
    story_ref: str = "",
    adr_key: str = "",
    scope: str = "project",
    visibility: str = "project",
    tags_json: str = "[]",
) -> str:
    """Store ADR/MADR (:Decision), optional DECIDED_IN→Story; scope/visibility/tags cho ES."""
    pid = int(project_id)
    if pid <= 0:
        raise ValueError("project_id required")
    tit = (title or "").strip()
    if not tit:
        raise ValueError("title required")
    key_src = (adr_key or "").strip() or hashlib.sha256(tit.encode()).hexdigest()[:16]
    decision_num = int(key_src[:12], 16) % (10**12)
    dref = node_ref(pid, "decision", decision_num)
    ts = datetime.now(timezone.utc).isoformat()
    sref = (story_ref or "").strip()
    tags = _parse_tags_json(tags_json)
    sc = (scope or "project").strip()[:32] or "project"
    vis = (visibility or "project").strip()[:32] or "project"
    st = (status or "Proposed")[:64]
    run_write(
        """
        MERGE (d:Decision {ref: $dref})
        SET d.project_id = $pid, d.title = $title, d.status = $st, d.context = $context,
            d.decision = $decision, d.consequences = $consequences, d.adr_key = $adr_key,
            d.scope = $scope, d.visibility = $visibility, d.tags = $tags, d.ingested_at = $ts
        """,
        {
            "dref": dref,
            "pid": pid,
            "title": tit[:2000],
            "st": st,
            "context": (context or "")[:16000],
            "decision": (decision or "")[:8000],
            "consequences": (consequences or "")[:8000],
            "adr_key": key_src[:128],
            "scope": sc,
            "visibility": vis,
            "tags": tags,
            "ts": ts,
        },
    )
    if sref:
        run_write(
            """
            MATCH (d:Decision {ref: $dref}), (s:Story {ref: $sref})
            WHERE d.project_id = $pid AND s.project_id = $pid
            MERGE (d)-[:DECIDED_IN]->(s)
            """,
            {"dref": dref, "sref": sref, "pid": pid},
        )
    blob = "\n".join([tit, st, context, decision, consequences])
    es_store.index_chunk(
        project_id=pid,
        ref=dref,
        label="Decision",
        text=blob,
        event_type="brain_remember_decision",
        scope=sc,
        visibility=vis,
        status=st,
        tags=tags,
    )
    return json.dumps({"ok": True, "ref": dref}, ensure_ascii=False)


@mcp.tool()
def brain_remember_lesson(
    title: str,
    project_id: int,
    problem: str = "",
    what_we_learned: str = "",
    recommended_action: str = "",
    tags_json: str = "[]",
    derived_from_ref: str = "",
    scope: str = "project",
    visibility: str = "project",
) -> str:
    """Ghi :LessonLearned; optional DERIVED_FROM→nút nguồn (comment/ref khác)."""
    pid = int(project_id)
    if pid <= 0:
        raise ValueError("project_id required")
    tit = (title or "").strip()
    if not tit:
        raise ValueError("title required")
    tags = _parse_tags_json(tags_json)
    key_src = hashlib.sha256(tit.encode()).hexdigest()[:16]
    lesson_num = int(key_src[:12], 16) % (10**12)
    lref = node_ref(pid, "lesson", lesson_num)
    ts = datetime.now(timezone.utc).isoformat()
    sc = (scope or "project").strip()[:32] or "project"
    vis = (visibility or "project").strip()[:32] or "project"
    src = (derived_from_ref or "").strip()
    run_write(
        """
        MERGE (l:LessonLearned {ref: $lref})
        SET l.project_id = $pid, l.title = $title, l.problem = $problem, l.what_we_learned = $learned,
            l.recommended_action = $action, l.tags = $tags, l.scope = $scope, l.visibility = $visibility,
            l.ingested_at = $ts
        """,
        {
            "lref": lref,
            "pid": pid,
            "title": tit[:2000],
            "problem": (problem or "")[:16000],
            "learned": (what_we_learned or "")[:16000],
            "action": (recommended_action or "")[:8000],
            "tags": tags,
            "scope": sc,
            "visibility": vis,
            "ts": ts,
        },
    )
    if src:
        run_write(
            """
            MATCH (l:LessonLearned {ref: $lref}), (x {ref: $src})
            WHERE l.project_id = $pid AND x.project_id = $pid
            MERGE (l)-[:DERIVED_FROM]->(x)
            """,
            {"lref": lref, "src": src, "pid": pid},
        )
    blob = "\n".join([tit, problem, what_we_learned, recommended_action])
    es_store.index_chunk(
        project_id=pid,
        ref=lref,
        label="LessonLearned",
        text=blob,
        event_type="brain_remember_lesson",
        scope=sc,
        visibility=vis,
        tags=tags,
    )
    return json.dumps({"ok": True, "ref": lref}, ensure_ascii=False)


@mcp.tool()
def brain_extract_lesson_from_text(text: str) -> str:
    """P3: Trích JSON lesson (LLM nếu cấu hình env SECOND_BRAIN_EXTRACT_LLM_* , không thì heuristic)."""
    return json.dumps(propose_lesson_json(text or ""), ensure_ascii=False)


@mcp.tool()
def brain_extract_adr_from_text(text: str) -> str:
    """Trích JSON ADR/MADR (title,status,context,decision,consequences). Env SECOND_BRAIN_ADR_LLM_* hoặc SECOND_BRAIN_EXTRACT_LLM_*"""
    return json.dumps(propose_adr_json(text or ""), ensure_ascii=False)


@mcp.tool()
def brain_feedback_create(
    summary: str,
    project_id: int,
    detail: str = "",
    related_ref: str = "",
    scope: str = "project",
    visibility: str = "project",
) -> str:
    """Tạo :Feedback; optional PROVIDES_FEEDBACK→nút liên quan."""
    pid = int(project_id)
    if pid <= 0:
        raise ValueError("project_id required")
    sm = (summary or "").strip()
    if not sm:
        raise ValueError("summary required")
    key_src = hashlib.sha256(sm.encode()).hexdigest()[:16]
    fid = int(key_src[:12], 16) % (10**12)
    fref = node_ref(pid, "feedback", fid)
    ts = datetime.now(timezone.utc).isoformat()
    sc = (scope or "project").strip()[:32] or "project"
    vis = (visibility or "project").strip()[:32] or "project"
    rel_ref = (related_ref or "").strip()
    run_write(
        """
        MERGE (f:Feedback {ref: $fref})
        SET f.project_id = $pid, f.summary = $summary, f.detail = $detail,
            f.scope = $scope, f.visibility = $visibility, f.ingested_at = $ts
        """,
        {
            "fref": fref,
            "pid": pid,
            "summary": sm[:4000],
            "detail": (detail or "")[:16000],
            "scope": sc,
            "visibility": vis,
            "ts": ts,
        },
    )
    if rel_ref:
        run_write(
            """
            MATCH (f:Feedback {ref: $fref}), (x {ref: $rel})
            WHERE f.project_id = $pid AND x.project_id = $pid
            MERGE (f)-[:PROVIDES_FEEDBACK]->(x)
            """,
            {"fref": fref, "rel": rel_ref, "pid": pid},
        )
    es_store.index_chunk(
        project_id=pid,
        ref=fref,
        label="Feedback",
        text=f"{sm}\n{detail}",
        event_type="brain_feedback_create",
        scope=sc,
        visibility=vis,
    )
    return json.dumps({"ok": True, "ref": fref}, ensure_ascii=False)


@mcp.tool()
def brain_supersede_decision(old_decision_ref: str, new_decision_ref: str, project_id: int) -> str:
    """MERGE (new)-[:SUPERSEDES]->(old) trong cùng project."""
    pid = int(project_id)
    if pid <= 0:
        raise ValueError("project_id required")
    old_r = (old_decision_ref or "").strip()
    new_r = (new_decision_ref or "").strip()
    if not old_r or not new_r:
        raise ValueError("old_decision_ref and new_decision_ref required")
    run_write(
        """
        MATCH (new:Decision {ref: $new_r}), (old:Decision {ref: $old_r})
        WHERE new.project_id = $pid AND old.project_id = $pid
        SET old.status = 'Superseded'
        MERGE (new)-[:SUPERSEDES]->(old)
        """,
        {"new_r": new_r, "old_r": old_r, "pid": pid},
    )
    return json.dumps({"ok": True, "new": new_r, "old": old_r}, ensure_ascii=False)


def mcp_base_url() -> str:
    return f"http://{_MCP_HOST}:{_MCP_PORT}"


class _McpSecretGate(BaseHTTPMiddleware):
    """Khi đặt SECOND_BRAIN_MCP_SECRET: chỉ cho phép gọi endpoint MCP nếu Bearer hoặc header khớp."""

    def __init__(self, app: Any, *, secret: str, mcp_path: str):
        super().__init__(app)
        self._digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._mcp_base = (mcp_path or "/mcp").strip() or "/mcp"

    async def dispatch(self, request: Request, call_next: Any):  # noqa: ANN401
        path = request.url.path
        base = self._mcp_base.rstrip("/") or "/mcp"
        norm = path.rstrip("/") or "/"
        if norm != base and not path.startswith(base + "/"):
            return await call_next(request)

        bearer = (request.headers.get("authorization") or "").strip()
        token = ""
        if bearer.lower().startswith("bearer "):
            token = bearer[7:].strip()
        if not token:
            token = (request.headers.get("x-second-brain-mcp-secret") or "").strip()
        if not token:
            return JSONResponse({"error": "mcp_unauthorized"}, status_code=401)
        got = hashlib.sha256(token.encode("utf-8")).digest()
        if not hmac.compare_digest(got, self._digest):
            return JSONResponse({"error": "mcp_unauthorized"}, status_code=401)
        return await call_next(request)


def run() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    try:
        _boot_schema()
    except Exception as e:
        _log.warning("Schema bootstrap failed (will retry on first use): %s", e)
    transport = (os.environ.get("MCP_TRANSPORT", "stdio") or "stdio").strip().lower()
    if transport in ("http", "httpx", "http-streamable"):
        transport = "streamable-http"
    if transport == "stdio":
        print("Second Brain MCP: stdio mode.", file=sys.stderr)
        try:
            mcp.run(transport="stdio")
        finally:
            close_driver()
        return
    if transport == "streamable-http":
        import uvicorn

        path = getattr(mcp.settings, "streamable_http_path", "/mcp")
        starlette_app = mcp.streamable_http_app()
        mcp_secret = (os.environ.get("SECOND_BRAIN_MCP_SECRET") or "").strip()
        if mcp_secret:
            starlette_app.add_middleware(_McpSecretGate, secret=mcp_secret, mcp_path=_MCP_HTTP_PATH)
            print(
                f"Second Brain MCP: SHARED SECRET enabled for {path} "
                f"(Authorization: Bearer … hoặc X-Second-Brain-MCP-Secret)",
                file=sys.stderr,
            )
        print(
            f"Second Brain MCP (streamable HTTP): POST {mcp_base_url()}{path} — GET /health — "
            f"POST /ingest/agile-event — POST /ingest/github-webhook — POST /ingest/github-compare",
            file=sys.stderr,
        )
        try:
            uvicorn.run(
                starlette_app,
                host=mcp.settings.host,
                port=mcp.settings.port,
                log_level=mcp.settings.log_level.lower(),
            )
        finally:
            close_driver()
        return
    print(f"MCP_TRANSPORT={transport!r} unknown — using stdio.", file=sys.stderr)
    try:
        mcp.run(transport="stdio")
    finally:
        close_driver()