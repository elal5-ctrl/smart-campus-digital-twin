from collections.abc import Generator
from typing import Any

from sqlalchemy.engine import make_url
from sqlmodel import Session, create_engine

from app.core.config import get_settings

settings = get_settings()

connect_args: dict[str, Any] = {}
if make_url(settings.database_url).get_backend_name() == "postgresql":
    connect_args = {
        "connect_timeout": settings.database_connect_timeout_seconds,
        "options": (
            f"-c lock_timeout={settings.database_lock_timeout_ms} "
            f"-c statement_timeout={settings.database_statement_timeout_ms}"
        ),
    }

engine = create_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
    connect_args=connect_args,
)


def get_session() -> Generator[Session]:
    with Session(engine) as session:
        yield session
