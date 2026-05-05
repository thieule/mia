"""Embedding cho wiki: mặc định deterministic (độ dài cố định); tùy chọn HTTP (OpenAI-compatible)."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import urllib.error
import urllib.request
from typing import Any

EMBED_DIM = 384


def _deterministic_embedding(text: str, *, dim: int = EMBED_DIM) -> list[float]:
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


def _http_embedding(text: str, dim: int) -> list[float] | None:
    url = (os.environ.get("AGILE_EMBEDDING_HTTP_URL") or "").strip().rstrip("/")
    if not url:
        return None
    key = (os.environ.get("AGILE_EMBEDDING_HTTP_KEY") or "").strip()
    payload = json.dumps({"input": text[:12000], "model": os.environ.get("AGILE_EMBEDDING_MODEL") or "default"}).encode(
        "utf-8"
    )
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        data = json.loads(raw)
        emb = None
        if isinstance(data, dict):
            if "embedding" in data and isinstance(data["embedding"], list):
                emb = data["embedding"]
            elif "data" in data and isinstance(data["data"], list) and data["data"]:
                d0 = data["data"][0]
                if isinstance(d0, dict) and isinstance(d0.get("embedding"), list):
                    emb = d0["embedding"]
        if not emb or not isinstance(emb, list):
            return None
        nums = [float(x) for x in emb if isinstance(x, (int, float))]
        if len(nums) != dim:
            # pad or truncate to dim
            if len(nums) > dim:
                nums = nums[:dim]
            else:
                nums.extend([0.0] * (dim - len(nums)))
        norm = math.sqrt(sum(x * x for x in nums)) or 1.0
        return [x / norm for x in nums]
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, ValueError, TypeError):
        return None


def embed_text(text: str) -> list[float]:
    """Vector chuẩn hóa L2; 384 chiều (Elasticsearch dense_vector thường 384/768 — chỉnh dim nếu cần)."""
    dim = int(os.environ.get("AGILE_EMBEDDING_DIM") or EMBED_DIM)
    dim = max(32, min(dim, 4096))
    ext = _http_embedding(text, dim)
    if ext is not None:
        return ext
    return _deterministic_embedding(text, dim=dim)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x * y for x, y in zip(a, b))
