from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, Auth, Paging, get_analysis_or_404
from app.db.models import (
    Analysis,
    AnalysisStatus,
    Finding,
    FindingStatus,
    Patch,
    Repository,
    Severity,
    SourceFile,
)
from app.schemas.api import (
    AnalysisCreate,
    AnalysisOut,
    AnalysisSummary,
    QualityGate,
    RepositoryCreate,
    RepositoryOut,
    RepositoryOverview,
)
from app.services.github import GitHubClient, parse_repo_url
from app.worker.queue import enqueue
from app.worker.tasks import ANALYSIS

router = APIRouter(tags=["analyses"])


# ------------------------------------------------------------ repositories
@router.post("/repositories", response_model=RepositoryOut, status_code=201)
async def register_repository(payload: RepositoryCreate, db: DB, _: Auth):
    full_name = payload.full_name
    existing = (
        await db.execute(select(Repository).where(Repository.full_name == full_name))
    ).scalar_one_or_none()
    if existing:
        return existing

    owner, name = parse_repo_url(payload.url)
    default_branch = payload.default_branch or "main"
    is_private = False
    client = GitHubClient()
    try:
        meta = await client.get_repo(owner, name)
        default_branch = payload.default_branch or meta.get("default_branch", "main")
        is_private = bool(meta.get("private", False))
    except Exception:
        pass  # unauthenticated / rate limited: fall back to defaults
    finally:
        await client.aclose()

    repo = Repository(
        full_name=full_name,
        clone_url=f"https://github.com/{full_name}.git",
        default_branch=default_branch,
        is_private=is_private,
    )
    db.add(repo)
    await db.flush()
    _overview_cache.clear()
    return repo


@router.get("/repositories", response_model=list[RepositoryOut])
async def list_repositories(db: DB, _: Auth, paging: Paging):
    rows = (
        await db.execute(
            select(Repository)
            .order_by(Repository.created_at.desc())
            .limit(paging.limit)
            .offset(paging.offset)
        )
    ).scalars().all()
    return rows


_overview_cache: dict[str, tuple[float, list[RepositoryOverview]]] = {}
_OVERVIEW_CACHE_TTL: float = 8.0  # seconds


@router.get("/repositories/overview", response_model=list[RepositoryOverview])
async def repositories_overview(db: DB, _: Auth, paging: Paging):
    """The repositories table in one request: each repo with its latest run and
    what that run left behind. Declared before `/repositories/{id}` so the
    literal path is not swallowed by the UUID route."""
    global _overview_cache
    now = time.monotonic()
    cache_key = f"{paging.offset}:{paging.limit}"
    if cache_key in _overview_cache:
        cached_time, cached_rows = _overview_cache[cache_key]
        if (now - cached_time) < _OVERVIEW_CACHE_TTL:
            return cached_rows

    repos = (
        await db.execute(
            select(Repository)
            .order_by(Repository.created_at.desc())
            .limit(paging.limit)
            .offset(paging.offset)
        )
    ).scalars().all()

    if not repos:
        return []

    repo_ids = [r.id for r in repos]
    latest_analyses = (
        await db.execute(
            select(Analysis)
            .distinct(Analysis.repository_id)
            .where(Analysis.repository_id.in_(repo_ids))
            .order_by(Analysis.repository_id, Analysis.created_at.desc())
        )
    ).scalars().all()

    last_by_repo_id = {a.repository_id: a for a in latest_analyses}
    analysis_ids = [a.id for a in latest_analyses]

    by_analysis_sev: dict[uuid.UUID, dict[str, int]] = {aid: {} for aid in analysis_ids}
    by_analysis_stat: dict[uuid.UUID, dict[str, int]] = {aid: {} for aid in analysis_ids}
    by_analysis_patches: dict[uuid.UUID, int] = {aid: 0 for aid in analysis_ids}
    if analysis_ids:
        f_res = await db.execute(
            select(Finding.analysis_id, Finding.severity, Finding.status, func.count())
            .where(Finding.analysis_id.in_(analysis_ids))
            .group_by(Finding.analysis_id, Finding.severity, Finding.status)
        )
        p_res = await db.execute(
            select(Patch.analysis_id, func.count())
            .where(Patch.analysis_id.in_(analysis_ids))
            .group_by(Patch.analysis_id)
        )

        for aid, s, stat, cnt in f_res.all():
            by_analysis_sev[aid][s] = by_analysis_sev[aid].get(s, 0) + cnt
            by_analysis_stat[aid][stat] = by_analysis_stat[aid].get(stat, 0) + cnt

        for aid, cnt in p_res.all():
            by_analysis_patches[aid] = cnt

    rows: list[RepositoryOverview] = []
    for repo in repos:
        overview = RepositoryOverview(repository=RepositoryOut.model_validate(repo))
        last = last_by_repo_id.get(repo.id)
        if last is not None:
            out = AnalysisOut.model_validate(last)
            out.repository_full_name = repo.full_name
            overview.last_analysis = out
            sev = by_analysis_sev.get(last.id, {})
            statuses = by_analysis_stat.get(last.id, {})
            overview.by_severity = sev
            overview.findings = sum(sev.values())
            overview.patched = by_analysis_patches.get(last.id, 0)
            overview.validated = statuses.get("validated", 0)
            overview.false_positives = statuses.get("false_positive", 0)
        rows.append(overview)
    _overview_cache[cache_key] = (now, rows)
    return rows


@router.get("/repositories/{repository_id}", response_model=RepositoryOut)
async def get_repository(repository_id: uuid.UUID, db: DB, _: Auth):
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(404, "Repository not found")
    return repo


# ---------------------------------------------------------------- analyses
@router.post("/analyses", response_model=AnalysisOut, status_code=202)
async def create_analysis(payload: AnalysisCreate, db: DB, _: Auth):
    """Queue an analysis. Returns immediately; poll GET /analyses/{id}."""
    repo: Repository | None = None
    if payload.repository_id:
        repo = await db.get(Repository, payload.repository_id)
    elif payload.url:
        created = await register_repository(RepositoryCreate(url=payload.url), db, "internal")
        repo = created
    if repo is None:
        raise HTTPException(400, "Provide either repository_id or url")

    analysis = Analysis(
        repository_id=repo.id,
        branch=payload.branch or repo.default_branch,
        commit_sha=payload.commit_sha,
        pr_number=payload.pr_number,
        trigger="pull_request" if payload.pr_number else "manual",
        status=AnalysisStatus.QUEUED,
        diff_only=payload.diff_only,
        stats={"options": {"open_pr": payload.open_pr, "categories": payload.categories}},
    )
    db.add(analysis)
    await db.flush()
    _overview_cache.clear()
    await enqueue(ANALYSIS, {"analysis_id": str(analysis.id)})
    return analysis


@router.get("/analyses", response_model=list[AnalysisOut])
async def list_analyses(
    db: DB, _: Auth, paging: Paging,
    repository_id: uuid.UUID | None = None,
    status: str | None = None,
):
    stmt = (
        select(Analysis)
        .options(selectinload(Analysis.repository))
        .order_by(Analysis.created_at.desc())
    )
    if repository_id:
        stmt = stmt.where(Analysis.repository_id == repository_id)
    if status:
        stmt = stmt.where(Analysis.status == status)
    rows = (await db.execute(stmt.limit(paging.limit).offset(paging.offset))).scalars().all()
    return rows


@router.get("/analyses/{analysis_id}", response_model=AnalysisOut)
async def get_analysis(analysis: Analysis = Depends(get_analysis_or_404), _: Auth = None):
    return analysis


@router.get("/analyses/{analysis_id}/summary", response_model=AnalysisSummary)
async def analysis_summary(db: DB, _: Auth, analysis: Analysis = Depends(get_analysis_or_404)):
    """Everything the dashboard needs in one request."""
    findings_res = await db.execute(
        select(Finding.severity, Finding.category, func.count())
        .where(Finding.analysis_id == analysis.id)
        .group_by(Finding.severity, Finding.category)
    )
    patches_res = await db.execute(
        select(Patch.status, func.count())
        .where(Patch.analysis_id == analysis.id)
        .group_by(Patch.status)
    )
    top_files_res = await db.execute(
        select(Finding.path, func.count())
        .where(Finding.analysis_id == analysis.id)
        .group_by(Finding.path)
        .order_by(func.count().desc())
        .limit(10)
    )

    sev: dict[str, int] = {}
    cat: dict[str, int] = {}
    for s, c, cnt in findings_res.all():
        sev[s] = sev.get(s, 0) + cnt
        cat[c] = cat.get(c, 0) + cnt

    patches = dict(patches_res.all())
    top_files = [{"path": p, "findings": c} for p, c in top_files_res.all()]

    return AnalysisSummary(
        analysis=AnalysisOut.model_validate(analysis),
        repository=(
            RepositoryOut.model_validate(analysis.repository)
            if analysis.repository is not None
            else None
        ),
        findings_by_severity=sev,
        findings_by_category=cat,
        patches=patches,
        top_files=top_files,
    )


@router.get("/analyses/{analysis_id}/files")
async def analysis_files(db: DB, _: Auth, analysis: Analysis = Depends(get_analysis_or_404)):
    rows = (
        await db.execute(
            select(SourceFile)
            .where(SourceFile.analysis_id == analysis.id)
            .order_by(SourceFile.loc.desc())
            .limit(500)
        )
    ).scalars().all()
    return [
        {"path": r.path, "language": r.language, "loc": r.loc, "parse_error": r.parse_error}
        for r in rows
    ]


@router.get("/analyses/{analysis_id}/graph")
async def analysis_graph(db: DB, _: Auth, analysis: Analysis = Depends(get_analysis_or_404)):
    """Nodes/edges for the frontend dependency visualisation."""
    graph = (analysis.stats or {}).get("graph", {})
    return {
        "metrics": graph,
        "cycles": (analysis.stats or {}).get("dependency_cycles", 0),
        "project": (analysis.stats or {}).get("project", {}),
        "languages": (analysis.stats or {}).get("languages", {}),
    }


@router.get("/analyses/{analysis_id}/gate", response_model=QualityGate)
async def quality_gate(
    db: DB,
    _: Auth,
    analysis: Analysis = Depends(get_analysis_or_404),
    fail_on: str = Query(
        "high",
        description="Lowest severity that blocks the build: critical|high|medium|low|info",
    ),
):
    """Poll target for CI. Returns `complete` once the run has finished and
    `passed` once the blocking findings have been counted.

    False positives and findings a reviewer rejected never block a build — the
    gate is only as credible as the reviewer's ability to overrule it.
    """
    floor = Severity.ORDER.get(fail_on.lower(), Severity.ORDER[Severity.HIGH])
    blocking_severities = [s for s, rank in Severity.ORDER.items() if rank >= floor]

    counts_res = await db.execute(
        select(Finding.severity, func.count())
        .where(Finding.analysis_id == analysis.id)
        .group_by(Finding.severity)
    )
    patches_res = await db.execute(
        select(Patch.status, func.count())
        .where(Patch.analysis_id == analysis.id)
        .group_by(Patch.status)
    )
    blocking_res = await db.execute(
        select(func.count())
        .select_from(Finding)
        .where(
            Finding.analysis_id == analysis.id,
            Finding.severity.in_(blocking_severities),
            Finding.status.notin_([FindingStatus.FALSE_POSITIVE, FindingStatus.REJECTED]),
        )
    )
    counts = dict(counts_res.all())
    patches = dict(patches_res.all())
    blocking = blocking_res.scalar_one()

    complete = analysis.status in (
        AnalysisStatus.SUCCEEDED,
        AnalysisStatus.FAILED,
        AnalysisStatus.CANCELLED,
    )
    return QualityGate(
        analysis_id=analysis.id,
        status=analysis.status,
        complete=complete,
        # A run that never finished is not a pass.
        passed=complete and analysis.status == AnalysisStatus.SUCCEEDED and blocking == 0,
        stage=analysis.stage,
        progress=analysis.progress,
        fail_on=fail_on.lower(),
        blocking_findings=blocking,
        counts=counts,
        patches=patches,
        error=analysis.error,
    )


@router.delete("/analyses/{analysis_id}", status_code=204)
async def delete_analysis(db: DB, _: Auth, analysis: Analysis = Depends(get_analysis_or_404)):
    await db.delete(analysis)
    _overview_cache.clear()
