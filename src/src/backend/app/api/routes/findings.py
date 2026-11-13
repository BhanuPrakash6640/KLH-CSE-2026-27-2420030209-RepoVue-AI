from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, Auth, Paging
from app.db.models import (
    Finding,
    FindingStatus,
    JiraTicket,
    Patch,
    PatchStatus,
    ValidationRun,
)
from app.schemas.api import (
    FindingDetail,
    FindingPage,
    FindingStatusUpdate,
    PatchOut,
    SearchHit,
    SearchRequest,
    ValidationOut,
)
from app.services.retrieval import hybrid_search

router = APIRouter(tags=["findings"])


@router.get("/findings", response_model=FindingPage)
async def list_findings(
    db: DB, _: Auth, paging: Paging,
    analysis_id: uuid.UUID | None = None,
    severity: str | None = None,
    category: str | None = None,
    status: str | None = None,
    path: str | None = None,
    q: str | None = Query(None, description="Substring match on title"),
):
    stmt = select(Finding)
    count_stmt = select(func.count()).select_from(Finding)
    for clause in [
        Finding.analysis_id == analysis_id if analysis_id else None,
        Finding.severity == severity if severity else None,
        Finding.category == category if category else None,
        Finding.status == status if status else None,
        Finding.path.ilike(f"%{path}%") if path else None,
        Finding.title.ilike(f"%{q}%") if q else None,
    ]:
        if clause is not None:
            stmt = stmt.where(clause)
            count_stmt = count_stmt.where(clause)

    total = (await db.execute(count_stmt)).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Finding.severity, Finding.created_at.desc())
            .limit(paging.limit)
            .offset(paging.offset)
        )
    ).scalars().all()
    return FindingPage(total=total, limit=paging.limit, offset=paging.offset, items=rows)


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def get_finding(finding_id: uuid.UUID, db: DB, _: Auth):
    finding = (
        await db.execute(
            select(Finding).where(Finding.id == finding_id).options(selectinload(Finding.patches))
        )
    ).scalar_one_or_none()
    if finding is None:
        raise HTTPException(404, "Finding not found")
    return finding


@router.patch("/findings/{finding_id}", response_model=FindingDetail)
async def update_finding_status(
    finding_id: uuid.UUID, payload: FindingStatusUpdate, db: DB, _: Auth
):
    """Human feedback loop. Marking false positives is what lets you measure
    precision honestly instead of guessing at it."""
    finding = (
        await db.execute(
            select(Finding).where(Finding.id == finding_id).options(selectinload(Finding.patches))
        )
    ).scalar_one_or_none()
    if finding is None:
        raise HTTPException(404, "Finding not found")
    finding.status = payload.status
    if payload.note:
        finding.evidence = {**(finding.evidence or {}), "reviewer_note": payload.note[:1000]}
    await db.flush()
    return finding


@router.get("/findings/{finding_id}/jira")
async def finding_ticket(finding_id: uuid.UUID, db: DB, _: Auth):
    ticket = (
        await db.execute(select(JiraTicket).where(JiraTicket.finding_id == finding_id))
    ).scalar_one_or_none()
    if ticket is None:
        raise HTTPException(404, "No Jira ticket linked to this finding")
    return {"key": ticket.issue_key, "url": ticket.url, "status": ticket.status}


# ------------------------------------------------------------------ patches
@router.get("/patches", response_model=list[PatchOut])
async def list_patches(
    db: DB, _: Auth, paging: Paging,
    analysis_id: uuid.UUID | None = None,
    status: str | None = None,
):
    stmt = select(Patch)
    if analysis_id:
        stmt = stmt.where(Patch.analysis_id == analysis_id)
    if status:
        stmt = stmt.where(Patch.status == status)
    return (
        await db.execute(stmt.order_by(Patch.created_at.desc()).limit(paging.limit).offset(paging.offset))
    ).scalars().all()


@router.get("/patches/{patch_id}", response_model=PatchOut)
async def get_patch(patch_id: uuid.UUID, db: DB, _: Auth):
    patch = await db.get(Patch, patch_id)
    if patch is None:
        raise HTTPException(404, "Patch not found")
    return patch


@router.get("/patches/{patch_id}/validations", response_model=list[ValidationOut])
async def patch_validations(patch_id: uuid.UUID, db: DB, _: Auth):
    return (
        await db.execute(
            select(ValidationRun)
            .where(ValidationRun.patch_id == patch_id)
            .order_by(ValidationRun.created_at.desc())
        )
    ).scalars().all()


@router.post("/patches/{patch_id}/decision", response_model=PatchOut)
async def decide_patch(patch_id: uuid.UUID, db: DB, _: Auth, accept: bool = Query(...)):
    patch = await db.get(Patch, patch_id)
    if patch is None:
        raise HTTPException(404, "Patch not found")
    patch.status = PatchStatus.ACCEPTED if accept else PatchStatus.REJECTED
    finding = await db.get(Finding, patch.finding_id)
    if finding:
        finding.status = FindingStatus.VALIDATED if accept else FindingStatus.REJECTED
    await db.flush()
    return patch


# ------------------------------------------------------------------- search
@router.post("/search", response_model=list[SearchHit])
async def semantic_search(payload: SearchRequest, db: DB, _: Auth):
    """Hybrid vector + lexical search over an analysed codebase."""
    hits = await hybrid_search(db, payload.analysis_id, payload.query, payload.limit)
    return [
        SearchHit(
            path=c.path, symbol_name=c.symbol_name, start_line=c.start_line,
            end_line=c.end_line, score=score, content=c.content[:4000],
        )
        for c, score in hits
    ]
