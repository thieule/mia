"""Embeddings qua Gemini API (text-embedding mặc định); fallback deterministic chỉ khi bật cờ dev."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import struct
import time
import urllib.error
import urllib.request

_log = logging.getLogger(__name__)

# Chiều vector lưu trong Elasticsearch (khớp outputDimensionality của Gemini khi set).
EMBED_DIM = int((os.environ.get("SECOND_BRAIN_EMBED_DIM") or "384").strip() or "384")


def _embed_deterministic(text: str, *, dim: int) -> list[float]:
    """Fallback offline — không thay thế semantic search thật; chỉ dev/CI."""
    t = (text or "").strip().lower()
    if not t:
        return [0.0] * dim
    chunk = t[:12000]
    out = [0.0] * dim
    for i in range(dim):
        seed = f"{i}:{chunk}".encode("utf-8", errors="ignore")
        h = hashlib.blake2b(seed, digest_size=4).digest()
        u = struct.unpack(">I", h)[0]
        out[i] = (u / 4294967295.0) * 2.0 - 1.0
    norm = math.sqrt(sum(x * x for x in out)) or 1.0
    return [x / norm for x in out]


def _parse_embedding_response(raw: dict) -> list[float]:
    emb = raw.get("embedding")
    if isinstance(emb, dict) and "values" in emb:
        vals = emb["values"]
        if isinstance(vals, list):
            return [float(x) for x in vals]
    if isinstance(emb, list):
        return [float(x) for x in emb]
    raise ValueError("unexpected embedding shape in Gemini response")


def _embed_gemini_rest(text: str, *, output_dim: int) -> list[float]:
    api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("missing GEMINI_API_KEY or GOOGLE_API_KEY")

    model_raw = (os.environ.get("SECOND_BRAIN_GEMINI_EMBED_MODEL") or "text-embedding-004").strip()
    model = model_raw if model_raw.startswith("models/") else f"models/{model_raw}"

    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:embedContent?key={api_key}"
    body: dict = {
        "model": model,
        "content": {"parts": [{"text": (text or "")[:12000]}]},
        "taskType": "RETRIEVAL_DOCUMENT",
        "outputDimensionality": output_dim,
    }
    body_bytes = json.dumps(body).encode("utf-8")
    max_retries = max(1, int((os.environ.get("SECOND_BRAIN_EMBED_MAX_RETRIES") or "3").strip() or "3"))
    backoff = float((os.environ.get("SECOND_BRAIN_EMBED_RETRY_DELAY_SEC") or "1.25").strip() or "1.25")

    payload: dict | None = None
    last_http: urllib.error.HTTPError | None = None
    for attempt in range(max_retries):
        req = urllib.request.Request(
            url,
            data=body_bytes,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
            break
        except urllib.error.HTTPError as e:
            last_http = e
            err_body = e.read().decode("utf-8", errors="replace") if e.fp else ""
            retryable = e.code in (408, 429, 500, 502, 503, 504)
            if not retryable or attempt >= max_retries - 1:
                _log.warning("Gemini embed HTTP %s: %s", e.code, err_body[:500])
                raise RuntimeError(f"Gemini embedContent failed: HTTP {e.code}") from e
            _log.warning(
                "Gemini embed HTTP %s, retry %s/%s in %.1fs",
                e.code,
                attempt + 1,
                max_retries,
                backoff * (attempt + 1),
            )
            time.sleep(backoff * (attempt + 1))
        except urllib.error.URLError as e:
            if attempt >= max_retries - 1:
                raise RuntimeError(f"Gemini embedContent network error: {e}") from e
            _log.warning("Gemini embed URLError, retry %s/%s: %s", attempt + 1, max_retries, e)
            time.sleep(backoff * (attempt + 1))

    if payload is None:
        raise RuntimeError("Gemini embedContent failed after retries") from last_http

    vec = _parse_embedding_response(payload)
    if len(vec) != output_dim:
        _log.warning("embedding length %s != expected %s", len(vec), output_dim)
    return vec


def embed_text(text: str, *, dim: int | None = None) -> list[float]:
    """
    Vector hóa văn bản cho ES kNN.

    - **Mặc định:** Gemini Embedding API (`SECOND_BRAIN_GEMINI_EMBED_MODEL`, mặc định `text-embedding-004`),
      `outputDimensionality` = `SECOND_BRAIN_EMBED_DIM` (mặc định **384** để khớp index hiện có).
    - **Offline:** đặt `SECOND_BRAIN_EMBEDDING_FALLBACK=1` khi không có API key → vector deterministic (không nên dùng production).
    """
    target_dim = int(dim if dim is not None else EMBED_DIM)
    use_fallback = (os.environ.get("SECOND_BRAIN_EMBEDDING_FALLBACK") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    has_key = bool((os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip())

    if has_key:
        return _embed_gemini_rest(text, output_dim=target_dim)
    if use_fallback:
        _log.warning(
            "using deterministic embedding fallback (no API key); set GEMINI_API_KEY for Gemini semantic search"
        )
        return _embed_deterministic(text, dim=target_dim)
    raise RuntimeError(
        "Gemini embedding requires GEMINI_API_KEY or GOOGLE_API_KEY. "
        "For offline dev only, set SECOND_BRAIN_EMBEDDING_FALLBACK=1 "
        "(deterministic vectors — not semantic quality)."
    )
