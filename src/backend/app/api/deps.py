from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Analysis, Repository
from app.db.session import get_db

DB = Annotated[AsyncSession, Depends(get_db)]


async def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if not settings.api_key_set:
        return "anonymous"
    if x_api_key not in settings.api_key_set:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key header",
        )
    return x_api_key


Auth = Annotated[str, Depends(require_api_key)]


class Pagination:
    def __init__(
        self,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> None:
        self.limit = limit
        self.offset = offset


Paging = Annotated[Pagination, Depends(Pagination)]


async def get_analysis_or_404(analysis_id: uuid.UUID, db: DB) -> Analysis:
    # The repository is eager-loaded because every response that carries an
    # analysis also carries `owner/repo` for the header.
    analysis = (
        await db.execute(
            select(Analysis)
            .where(Analysis.id == analysis_id)
            .options(selectinload(Analysis.repository))
        )
    ).scalar_one_or_none()
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


async def get_repository_or_404(repository_id: uuid.UUID, db: DB) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
