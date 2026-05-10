"""Read-only Cypher guard for agent-facing graph queries."""

from __future__ import annotations

import re

_FORBIDDEN = re.compile(
    r"\b("
    r"CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|INSERT|LOAD\s+CSV|"
    r"GRANT|DENY|REVOKE|ALTER|CALL\s+dbms|CALL\s+apoc\.|"
    r"FOREACH|USING\s+PERIODIC"
    r")\b",
    re.IGNORECASE | re.DOTALL,
)


def assert_read_only_cypher(cypher: str, *, max_len: int = 12000) -> None:
    q = (cypher or "").strip()
    if not q:
        raise ValueError("Empty Cypher query")
    if len(q) > max_len:
        raise ValueError(f"Cypher exceeds max length ({max_len})")
    if ";" in q.rstrip(";"):
        raise ValueError("Only a single Cypher statement is allowed")
    if _FORBIDDEN.search(q):
        raise ValueError("Only read-only Cypher is allowed (no CREATE/MERGE/DELETE/SET/…)")
