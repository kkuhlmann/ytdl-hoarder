from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel

from config import settings


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        self._async_engine = None
        self._sync_engine = None
        self._async_session_factory = None
        self._sync_session_factory = None

    @property
    def async_engine(self):
        return self._async_engine

    @property
    def sync_engine(self):
        return self._sync_engine

    def initialize_database(self):
        base_url = self.database_url

        if base_url.startswith('postgresql://'):
            async_url = base_url.replace('postgresql://', 'postgresql+asyncpg://', 1)
            sync_url = base_url.replace('postgresql://', 'postgresql+psycopg://', 1)
        else:
            async_url = base_url
            sync_url = base_url

        # The async engine is only used by the single async process, so pooling
        # is safe here and avoids a new TCP connection per query.
        self._async_engine = create_async_engine(
            async_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
        )

        # Sync engine for job bodies (lane threads + the ML child). Pooled so connections and
        # their `postgres` DNS lookup are reused instead of re-opened per query;
        # the ML child re-inits the engine inside its own process at bootstrap
        # (child_main). pool_pre_ping replaces stale connections transparently.
        self._sync_engine = create_engine(
            sync_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
            pool_pre_ping=True,
        )

        self._async_session_factory = async_sessionmaker(
            bind=self._async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self._sync_session_factory = sessionmaker(
            bind=self._sync_engine,
            expire_on_commit=False,
        )

    async def create_tables(self):
        async with self._async_engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def get_async_session(self) -> AsyncGenerator[AsyncSession]:
        """Get an async session for FastAPI routes."""
        async with self._async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    @contextmanager
    def sync_session(self) -> Generator[Session]:
        """Get a sync session for job bodies (lane threads / ML child).

        Mirrors get_async_session: auto-commits on success, rolls back on
        exception, and always closes the session.
        """
        session = self._sync_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def use_async_session(
        self, session: AsyncSession | None = None
    ) -> AsyncGenerator[AsyncSession]:
        """Yield the given session, or open a new one if None.

        With a caller-provided session, statements join the caller's transaction
        and nothing is committed here. Without one, behaves like
        get_async_session (commit on success, rollback on exception).
        """
        if session is not None:
            yield session
        else:
            async with self.get_async_session() as new_session:
                yield new_session

    @contextmanager
    def use_sync_session(self, session: Session | None = None) -> Generator[Session]:
        """Sync mirror of use_async_session."""
        if session is not None:
            yield session
        else:
            with self.sync_session() as new_session:
                yield new_session

    def get_sync_session(self) -> Session:
        """Get a raw sync session for job bodies.

        IMPORTANT: Caller is responsible for commit/rollback/close.
        Prefer sync_session() context manager instead.
        """
        return self._sync_session_factory()

    async def close(self):
        if self._async_engine:
            await self._async_engine.dispose()
        if self._sync_engine:
            self._sync_engine.dispose()


db = Database(database_url=settings.database.url)
