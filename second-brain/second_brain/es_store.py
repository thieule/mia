from __future__ import annotations

import logging
import os
from typing import Any

from elasticsearch import Elasticsearch

from second_brain.embeddings import EMBED_DIM, embed_text

_log = logging.getLogger(__name__)
_ES: Elasticsearch | None = None
INDEX_NAME = (os.environ.get("SECOND_BRAIN_ES_INDEX") or "second_brain_chunks").strip()

_BASE_PROPERTIES: dict[str, Any] = {
    "project_id": {"type": "keyword"},
    "ref": {"type": "keyword"},
    "label": {"type": "keyword"},
    "event_type": {"type": "keyword"},
    "source_type": {"type": "keyword"},
    "text": {"type": "text"},
    "scope": {"type": "keyword"},
    "visibility": {"type": "keyword"},
    "status": {"type": "keyword"},
    "tags": {"type": "keyword"},
    "embedding": {
        "type": "dense_vector",
        "dims": EMBED_DIM,
        "index": True,
        "similarity": "cosine",
    },
}

_MAPPING_UPGRADE: dict[str, Any] = {
    "scope": {"type": "keyword"},
    "visibility": {"type": "keyword"},
    "status": {"type": "keyword"},
    "tags": {"type": "keyword"},
    "source_type": {"type": "keyword"},
}


def es_client() -> Elasticsearch:
    global _ES
    if _ES is not None:
        return _ES
    url = (os.environ.get("ELASTICSEARCH_URL") or "http://127.0.0.1:9200").strip()
    _ES = Elasticsearch(url, request_timeout=30)
    return _ES


def ensure_index(client: Elasticsearch) -> None:
    if not client.indices.exists(index=INDEX_NAME):
        client.indices.create(index=INDEX_NAME, mappings={"properties": _BASE_PROPERTIES})
        return
    try:
        client.indices.put_mapping(index=INDEX_NAME, properties=dict(_MAPPING_UPGRADE))
    except Exception as e:
        _log.debug("ES put_mapping (non-fatal): %s", e)


def _filter_clauses(
    *,
    project_id: int | None,
    scope: str | None,
    visibility: str | None,
    source_type: str | None,
) -> list[dict[str, Any]]:
    must: list[dict[str, Any]] = []
    if project_id is not None:
        must.append({"term": {"project_id": str(project_id)}})
    if scope:
        must.append({"term": {"scope": scope}})
    if visibility:
        must.append({"term": {"visibility": visibility}})
    if source_type:
        must.append({"term": {"source_type": source_type}})
    return must


def index_chunk(
    *,
    project_id: int,
    ref: str,
    label: str,
    text: str,
    event_type: str = "",
    scope: str = "project",
    visibility: str = "project",
    status: str = "",
    tags: list[str] | None = None,
    source_type: str = "agile",
) -> None:
    client = es_client()
    ensure_index(client)
    vec = embed_text(text)
    doc_id = ref.replace(":", "_").replace("/", "_")
    tag_list = [str(t).strip() for t in (tags or []) if str(t).strip()][:50]
    st = (source_type or "agile").strip()[:32] or "agile"
    client.index(
        index=INDEX_NAME,
        id=doc_id,
        document={
            "project_id": str(max(0, int(project_id))),
            "ref": ref,
            "label": label,
            "event_type": event_type,
            "source_type": st,
            "text": text[:50000],
            "scope": (scope or "project")[:32],
            "visibility": (visibility or "project")[:32],
            "status": (status or "")[:64],
            "tags": tag_list,
            "embedding": vec,
        },
        refresh=True,
    )


def search_knn(
    *,
    query_text: str,
    project_id: int | None,
    top_k: int = 12,
    num_candidates: int = 50,
    scope: str | None = None,
    visibility: str | None = None,
    source_type: str | None = None,
    query_vector: list[float] | None = None,
) -> list[dict[str, Any]]:
    client = es_client()
    ensure_index(client)
    qv = query_vector if query_vector is not None else embed_text(query_text)
    knn: dict[str, Any] = {
        "field": "embedding",
        "query_vector": qv,
        "k": top_k,
        "num_candidates": max(num_candidates, top_k * 4),
    }
    must = _filter_clauses(
        project_id=project_id,
        scope=scope,
        visibility=visibility,
        source_type=source_type,
    )
    if must:
        knn["filter"] = {"bool": {"must": must}}

    resp = client.search(index=INDEX_NAME, knn=knn, size=top_k)
    hits = resp.get("hits", {}).get("hits", [])
    return _hits_to_list(hits)


def _hits_to_list(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("_source") or {}
        out.append(
            {
                "score": h.get("_score"),
                "ref": src.get("ref"),
                "label": src.get("label"),
                "project_id": src.get("project_id"),
                "scope": src.get("scope"),
                "visibility": src.get("visibility"),
                "status": src.get("status"),
                "tags": src.get("tags"),
                "source_type": src.get("source_type"),
                "text_preview": (src.get("text") or "")[:500],
                "event_type": src.get("event_type"),
            }
        )
    return out


def search_bm25(
    *,
    query_text: str,
    project_id: int | None,
    top_k: int = 12,
    scope: str | None = None,
    visibility: str | None = None,
    source_type: str | None = None,
) -> list[dict[str, Any]]:
    client = es_client()
    ensure_index(client)
    must = _filter_clauses(
        project_id=project_id,
        scope=scope,
        visibility=visibility,
        source_type=source_type,
    )
    must.append(
        {
            "multi_match": {
                "query": query_text,
                "fields": ["text^2", "label"],
                "type": "best_fields",
            }
        }
    )
    resp = client.search(
        index=INDEX_NAME,
        query={"bool": {"must": must}},
        size=top_k,
    )
    hits = resp.get("hits", {}).get("hits", [])
    return _hits_to_list(hits)


def search_hybrid(
    *,
    query_text: str,
    project_id: int | None,
    top_k: int = 12,
    num_candidates: int = 50,
    scope: str | None = None,
    visibility: str | None = None,
    source_type: str | None = None,
    vector_weight: float = 1.0,
    bm25_weight: float = 0.35,
) -> list[dict[str, Any]]:
    """kNN + BM25: gộp điểm theo ref (chuẩn hoá min-max đơn giản)."""
    qv = embed_text(query_text)
    vec_hits = search_knn(
        query_text=query_text,
        project_id=project_id,
        top_k=max(top_k * 2, 16),
        num_candidates=num_candidates,
        scope=scope,
        visibility=visibility,
        source_type=source_type,
        query_vector=qv,
    )
    txt_hits = search_bm25(
        query_text=query_text,
        project_id=project_id,
        top_k=max(top_k * 2, 16),
        scope=scope,
        visibility=visibility,
        source_type=source_type,
    )

    def _norm_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
        scores = [float(r.get("score") or 0) for r in rows]
        if not scores:
            return {}
        lo, hi = min(scores), max(scores)
        span = hi - lo or 1.0
        out: dict[str, float] = {}
        for r in rows:
            ref = str(r.get("ref") or "")
            if not ref:
                continue
            s = float(r.get("score") or 0)
            out[ref] = (s - lo) / span
        return out

    nv = _norm_scores(vec_hits)
    nb = _norm_scores(txt_hits)
    by_ref: dict[str, dict[str, Any]] = {}
    for r in vec_hits:
        ref = str(r.get("ref") or "")
        if ref:
            by_ref[ref] = {k: v for k, v in r.items() if k != "score"}
    for r in txt_hits:
        ref = str(r.get("ref") or "")
        if ref and ref not in by_ref:
            by_ref[ref] = {k: v for k, v in r.items() if k != "score"}

    ranked: list[tuple[float, dict[str, Any]]] = []
    for ref, row in by_ref.items():
        score = vector_weight * nv.get(ref, 0.0) + bm25_weight * nb.get(ref, 0.0)
        out = dict(row)
        out["ref"] = ref
        out["score"] = score
        ranked.append((score, out))
    ranked.sort(key=lambda x: -x[0])
    return [r for _, r in ranked[:top_k]]


def delete_by_ref(ref: str) -> None:
    client = es_client()
    if not client.indices.exists(index=INDEX_NAME):
        return
    doc_id = ref.replace(":", "_").replace("/", "_")
    try:
        client.delete(index=INDEX_NAME, id=doc_id, refresh=True)
    except Exception:
        pass
