from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def mcp_session() -> Session:
    """A short SQLAlchemy transaction (commit if OK, rollback if error)."""
    from agile_hub.db import configure_engine, get_engine

    configure_engine()
    SessionFactory = sessionmaker(autocommit=False, autoflush=False, bind=get_engine())
    db = SessionFactory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
