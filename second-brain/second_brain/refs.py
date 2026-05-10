"""Canonical ref strings for graph nodes."""

from __future__ import annotations

import re
import uuid


def node_ref(project_id: int, kind: str, agile_id: int) -> str:
    return f"p{project_id}:{kind.lower()}:{agile_id}"


def node_ref_slug(project_id: int, kind: str, external_id: str) -> str:
    """IDs không phải int (wiki doc/comment UUID)."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(external_id).strip())[:128]
    return f"p{project_id}:{kind.lower()}:{safe}"


def global_ref(kind: str, key: str | None = None) -> str:
    """Tri thức toàn tổ chức (không gắn một project Agile cụ thể)."""
    k = (key or "").strip() or uuid.uuid4().hex[:16]
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", k)[:128]
    return f"g:{kind.lower()}:{safe}"
