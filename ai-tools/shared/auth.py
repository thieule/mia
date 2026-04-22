"""Shared auth utilities for ai-tools MCP servers.

Stdio transport (current):
  validate_startup_secret() is called when each server starts.
  The secret is passed via the AI_TOOL_SECRET env var by mia's MCP config.
  If someone runs the server manually without the secret, it exits immediately.

HTTP transport (future):
  BearerAuthMiddleware is a Starlette middleware that checks
  'Authorization: Bearer <AI_TOOL_SECRET>' on every incoming request.
  Wire it in when switching transport to 'sse' or 'streamable-http'.
"""

from __future__ import annotations

import os
import sys


def get_secret() -> str:
    return os.environ.get("AI_TOOL_SECRET", "").strip()


def validate_startup_secret() -> None:
    """Exit if AI_TOOL_SECRET is not set. Call once at server startup."""
    if not get_secret():
        print(
            "ERROR: AI_TOOL_SECRET is not set. "
            "This server must be started by mia with the secret configured in .env.",
            file=sys.stderr,
        )
        sys.exit(1)


# --- HTTP bearer token middleware (for future HTTP/SSE transport) ---
try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class BearerAuthMiddleware(BaseHTTPMiddleware):
        """Reject requests that do not carry the correct Bearer token."""

        async def dispatch(self, request, call_next):
            secret = get_secret()
            if not secret:
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            if auth != f"Bearer {secret}":
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

except ImportError:
    # starlette not available — HTTP middleware not needed for stdio transport
    BearerAuthMiddleware = None  # type: ignore[assignment,misc]
