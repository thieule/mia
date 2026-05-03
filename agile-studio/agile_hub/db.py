from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import get_settings

Base = declarative_base()

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None
_configured_url: str | None = None


def configure_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal, _configured_url
    raw = (url or get_settings().database_url or "").strip()
    if not raw:
        raise RuntimeError("Missing AGILE_DATABASE_URL.")
    if _engine is not None and _configured_url == raw:
        return _engine
    _configured_url = raw
    kw: dict = {"pool_pre_ping": True}
    if raw.startswith("sqlite") and ":memory:" in raw:
        kw["poolclass"] = StaticPool
        kw["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(raw, **kw)
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return configure_engine()
    return _engine


def wait_for_db_ready(
    engine: Engine,
    *,
    max_attempts: int = 30,
    delay_s: float = 1.0,
) -> None:
    """Đợi MySQL sẵn sàng (tránh lỗi 2003 khi container MySQL vừa restart / chưa mở port 3306)."""
    log = logging.getLogger(__name__)
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError as e:
            last = e
            if attempt == 1 or attempt == max_attempts or attempt % 5 == 0:
                log.warning(
                    "Chờ MySQL: lần thử %d/%d — %s",
                    attempt,
                    max_attempts,
                    e,
                )
            if attempt < max_attempts:
                time.sleep(delay_s)
    if last is not None:
        raise last
    raise RuntimeError("wait_for_db_ready: no connection attempt made")


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Dùng cho background task (mỗi lần gọi một session/transaction riêng)."""
    if _SessionLocal is None:
        configure_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_session() -> Generator[Session, None, None]:
    if _SessionLocal is None:
        configure_engine()
    assert _SessionLocal is not None
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
