"""Create the pgvector extension, all tables and the ANN index.

Run with:  python -m app.db.init_db
For real deployments switch to Alembic; this keeps first-run setup one command.
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.config import settings
from app.db.models import Base
from app.db.session import engine
from app.logging_config import configure_logging, get_logger

log = get_logger(__name__)

VECTOR_INDEX = """
CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding
ON code_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
"""

TRGM_INDEX = """
CREATE INDEX IF NOT EXISTS ix_findings_title_trgm
ON findings USING gin (title gin_trgm_ops);
"""


async def init_db(drop: bool = False) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        if drop:
            log.warning("dropping_all_tables")
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text(VECTOR_INDEX))
        await conn.execute(text(TRGM_INDEX))
    log.info("db_ready", dim=settings.EMBEDDING_DIM)


if __name__ == "__main__":
    import sys

    configure_logging()
    asyncio.run(init_db(drop="--drop" in sys.argv))
