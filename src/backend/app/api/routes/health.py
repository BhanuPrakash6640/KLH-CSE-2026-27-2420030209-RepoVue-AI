from __future__ import annotations

import asyncio

from fastapi import APIRouter
from sqlalchemy import func, select, text

from app.api.deps import DB
from app.config import settings
from app.db.models import Analysis, Finding, Job, JobStatus, Repository
from app.schemas.api import Health
from app.services.sandbox import docker_available

router = APIRouter(tags=["system"])
VERSION = "1.0.0"


@router.get("/health", response_model=Health)
async def health(db: DB):
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except Exception as exc:
        database = f"error: {str(exc)[:120]}"

    docker = "ok" if await asyncio.to_thread(docker_available) else "unavailable"
    return Health(
        status="ok" if database == "ok" else "degraded",
        env=settings.ENV,
        database=database,
        llm_configured=bool(settings.GEMINI_API_KEY or settings.ANTHROPIC_API_KEY),
        docker=docker,
        version=VERSION,
    )


_metrics_cache: dict[str, object] = {}
_metrics_cache_time: float = 0.0
_METRICS_TTL: float = 15.0  # seconds


@router.get("/metrics")
async def metrics(db: DB):
    """Lightweight counters for the dashboard header and for evaluation."""
    global _metrics_cache, _metrics_cache_time
    import time
    now = time.monotonic()
    if _metrics_cache and (now - _metrics_cache_time) < _METRICS_TTL:
        return _metrics_cache

    scalar_stmt = select(
        select(func.count()).select_from(Repository).scalar_subquery().label("repositories"),
        select(func.count()).select_from(Analysis).scalar_subquery().label("analyses"),
        select(func.count()).select_from(Finding).scalar_subquery().label("findings"),
        select(func.count())
        .select_from(Finding)
        .where(Finding.status == "false_positive")
        .scalar_subquery()
        .label("false_positives"),
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.PENDING)
        .scalar_subquery()
        .label("jobs_pending"),
        select(func.count())
        .select_from(Job)
        .where(Job.status == JobStatus.FAILED)
        .scalar_subquery()
        .label("jobs_failed"),
    )
    sev_stmt = select(Finding.severity, func.count()).group_by(Finding.severity)

    scalar_res = await db.execute(scalar_stmt)
    sev_res = await db.execute(sev_stmt)
    row = scalar_res.mappings().one()
    sev = dict(sev_res.all())

    data = {
        "repositories": row["repositories"],
        "analyses": row["analyses"],
        "findings": row["findings"],
        "findings_by_severity": sev,
        "false_positives": row["false_positives"],
        "jobs_pending": row["jobs_pending"],
        "jobs_failed": row["jobs_failed"],
    }
    _metrics_cache = data
    _metrics_cache_time = now
    return data
