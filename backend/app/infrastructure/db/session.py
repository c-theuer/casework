from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _to_async_dsn(dsn: str) -> str:
    """config.py's db_dsn is a plain postgresql:// URL (the format every
    other tool -- psql, Cloud SQL docs, .env.example -- expects); SQLAlchemy's
    async engine needs the psycopg3 dialect spelled out explicitly."""
    if dsn.startswith("postgresql+"):
        return dsn
    return dsn.replace("postgresql://", "postgresql+psycopg://", 1)


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(_to_async_dsn(get_settings().db_dsn))
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def open_engine() -> None:
    # Engine/sessionmaker creation above is already lazy; this just forces it
    # to happen (and fail fast) at app startup rather than on first request.
    get_sessionmaker()


async def close_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


def set_sessionmaker(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    """Test hook: point the app at an already-configured sessionmaker (e.g.
    one bound to the integration-test database) instead of the lazily
    created default."""
    global _sessionmaker
    _sessionmaker = sessionmaker
