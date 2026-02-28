"""
Solasta — Supabase Client Initialisation

Provides both the Supabase REST client and an async SQLAlchemy engine
for direct PostgreSQL access when needed (e.g. complex queries).
"""

from __future__ import annotations

from supabase import create_client, Client
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ── Supabase REST Client ────────────────────────────────────

_supabase_client: Client | None = None


def get_supabase() -> Client:
    """Lazy-initialise and return the Supabase client."""
    global _supabase_client
    if _supabase_client is None:
        if not settings.supabase_url or not settings.supabase_key:
            logger.warning("supabase_not_configured", msg="Using local fallback database")
            raise RuntimeError("Supabase URL/Key not configured")
        _supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("supabase_connected", url=settings.supabase_url)
    return _supabase_client


# ── Async SQLAlchemy Engine (fallback / local dev) ──────────

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db_session() -> AsyncSession:
    """Yield an async database session."""
    async with async_session_factory() as session:
        yield session
