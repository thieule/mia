"""HTTP callback từ API Center để ghi reply agent vào chat-service (khi MCP không giao được)."""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from agile_hub.chat_api_center_bridge import ingest_api_center_agent_reply

from .deps import get_db

router = APIRouter(prefix="/integrations/api-center", tags=["api-center-callback"])


def _verify_agent_reply_bearer(authorization: str | None) -> None:
    exp = (os.environ.get("AGILE_AGENT_REPLY_TOKEN") or "").strip()
    if not exp:
        raise HTTPException(
            status_code=503,
            detail="Set AGILE_AGENT_REPLY_TOKEN (must match API Center API_CENTER_AGILE_REPLY_TOKEN)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    got = authorization[7:].strip()
    if not secrets.compare_digest(got, exp):
        raise HTTPException(status_code=403, detail="Invalid token")


@router.post("/agent-reply")
def api_center_agent_reply_ingest(
    payload: dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    """
    API Center POST cùng JSON ``reply_payload`` (sau ``_dispatch_reply``).
    Auth: ``Authorization: Bearer`` = ``AGILE_AGENT_REPLY_TOKEN`` (khớp ``API_CENTER_AGILE_REPLY_TOKEN`` bên API Center).
    """
    _verify_agent_reply_bearer(authorization)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    try:
        return ingest_api_center_agent_reply(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
