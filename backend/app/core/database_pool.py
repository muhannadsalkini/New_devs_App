import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
import logging

from ..config import settings

logger = logging.getLogger(__name__)

class DatabasePool:
    def __init__(self):
        self.engine = None
        self.session_factory = None
        
    async def initialize(self):
        """Initialize database connection pool"""
        if self.session_factory:
            return  # Already initialized — avoid recreating the engine per call.
        try:
            # BUGFIX: Build the async DSN from the real `database_url` setting
            # (which docker-compose supplies). The previous code referenced
            # `settings.supabase_db_*` attributes that don't exist, so the
            # pool failed to initialize and the service silently fell back to
            # hard-coded mock data — masking the real bugs.
            raw_url = settings.database_url
            if raw_url.startswith("postgresql://"):
                database_url = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
            elif raw_url.startswith("postgres://"):
                database_url = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
            else:
                database_url = raw_url

            
            # BUGFIX: don't pass `poolclass=QueuePool` here — SQLAlchemy's
            # async engine rejects the sync `QueuePool` and falls back to
            # `AsyncAdaptedQueuePool` automatically when omitted. The
            # previous code raised
            # "Pool class QueuePool cannot be used with asyncio engine"
            # on every request, which forced the mock-data fallback.
            self.engine = create_async_engine(
                database_url,
                pool_size=20,        # Base connections
                max_overflow=30,     # Burst headroom
                pool_pre_ping=True,  # Validate connections
                pool_recycle=3600,   # Recycle every hour
                echo=False,
            )

            
            self.session_factory = async_sessionmaker(
                bind=self.engine,
                class_=AsyncSession,
                expire_on_commit=False
            )
            
            logger.info("✅ Database connection pool initialized")
            
        except Exception as e:
            logger.error(f"❌ Database pool initialization failed: {e}")
            self.engine = None
            self.session_factory = None
    
    async def close(self):
        """Close database connections"""
        if self.engine:
            await self.engine.dispose()
    
    def get_session(self) -> AsyncSession:
        """Get database session from pool.

        BUGFIX: this used to be `async def` and just returned the session
        synchronously. Callers do `async with db_pool.get_session() as s:`,
        which then failed with
        "'coroutine' object does not support the asynchronous context
        manager protocol". Making it a plain sync method returns the
        `AsyncSession` (which IS an async context manager) directly.
        """
        if not self.session_factory:
            raise Exception("Database pool not initialized")
        return self.session_factory()


# Global database pool instance
db_pool = DatabasePool()

async def get_db_session() -> AsyncSession:
    """Dependency to get database session"""
    async with db_pool.get_session() as session:
        yield session
