"""Async SQLAlchemy engine + session factory.

The `connect` listener registers pgvector's asyncpg codec on every new
connection — without it asyncpg raises `invalid input for query argument`
the first time you insert an embedding.
"""
from __future__ import annotations

import ssl
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import numpy as np
from pgvector.asyncpg import register_vector
from pgvector.sqlalchemy import Vector as _BaseVector
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Adapt SQLAlchemy Vector bind processor for asyncpg binary codec
def _asyncpg_vector_bind(self, dialect):
    def process(value):
        if value is None:
            return None
        if isinstance(value, str):
            return [float(x) for x in value.strip("[]").split(",")]
        return np.asarray(value, dtype=">f4")
    return process

_BaseVector.bind_processor = _asyncpg_vector_bind

connect_args: dict = {"server_settings": {"application_name": "repovue"}}
if settings.DB_SSL:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    connect_args["ssl"] = ctx

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=False,
    pool_recycle=300,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    connect_args=connect_args,
)


@event.listens_for(engine.sync_engine, "connect")
def _register_pgvector(dbapi_connection, _record):  # pragma: no cover - driver glue
    try:
        dbapi_connection.run_async(register_vector)
    except Exception:
        pass


SessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """For background workers / scripts."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
