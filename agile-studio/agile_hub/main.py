"""Chạy API: ``cd agile-studio && PYTHONPATH=. uvicorn agile_hub.main:app --reload --port 9120``."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.agent_reply_router import router as agent_reply_router
from .api.auth_router import router as auth_router
from .api.router import router as api_router
from .config import get_settings
from .db import Base, configure_engine, get_engine, wait_for_db_ready


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_engine()
    from . import models  # noqa: F401 — đăng ký metadata

    eng = get_engine()
    await asyncio.to_thread(wait_for_db_ready, eng)
    await asyncio.to_thread(Base.metadata.create_all, eng)
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.api_title, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "agile-studio"}

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(agent_reply_router, prefix="/api/v1")
    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()


def run() -> None:
    import uvicorn

    s = get_settings()
    uvicorn.run(
        "agile_hub.main:app",
        host=s.listen_host,
        port=s.listen_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
