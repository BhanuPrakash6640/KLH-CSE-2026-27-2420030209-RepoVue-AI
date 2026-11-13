"""GitHub webhook receiver.

The quality gate that CI polls lives in `routes/analyses.py`, next to the rest
of the analysis endpoints."""
from __future__ import annotations


from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select

from app.api.deps import DB
from app.db.models import Analysis, AnalysisStatus, Repository
from app.logging_config import get_logger
from app.services.github import verify_webhook
from app.worker.queue import enqueue
from app.worker.tasks import ANALYSIS

router = APIRouter(tags=["integrations"])
log = get_logger(__name__)

TRIGGER_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


async def _upsert_repo(db: DB, payload: dict) -> Repository:
    repo_data = payload.get("repository") or {}
    full_name = repo_data.get("full_name")
    if not full_name:
        raise HTTPException(400, "payload has no repository.full_name")
    repo = (
        await db.execute(select(Repository).where(Repository.full_name == full_name))
    ).scalar_one_or_none()
    if repo is None:
        repo = Repository(
            full_name=full_name,
            clone_url=repo_data.get("clone_url") or f"https://github.com/{full_name}.git",
            default_branch=repo_data.get("default_branch", "main"),
            is_private=bool(repo_data.get("private")),
        )
        db.add(repo)
        await db.flush()
    return repo


@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    db: DB,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str | None = Header(default=None),
):
    body = await request.body()
    if not verify_webhook(body, x_hub_signature_256):
        raise HTTPException(401, "Invalid webhook signature")

    payload = await request.json()

    if x_github_event == "ping":
        return {"status": "pong"}

    if x_github_event == "pull_request":
        action = payload.get("action")
        if action not in TRIGGER_ACTIONS:
            return {"status": "ignored", "action": action}
        pr = payload["pull_request"]
        if pr.get("draft"):
            return {"status": "ignored", "reason": "draft PR"}
        repo = await _upsert_repo(db, payload)
        analysis = Analysis(
            repository_id=repo.id,
            commit_sha=pr["head"]["sha"],
            branch=pr["head"]["ref"],
            pr_number=pr["number"],
            trigger="pull_request",
            status=AnalysisStatus.QUEUED,
            diff_only=True,
            stats={"options": {"open_pr": False, "categories": [
                "logical_bug", "security", "performance", "architecture"
            ]}},
        )
        db.add(analysis)
        await db.flush()
        await enqueue(ANALYSIS, {"analysis_id": str(analysis.id)})
        return {"status": "queued", "analysis_id": str(analysis.id)}

    if x_github_event == "push":
        ref = payload.get("ref", "")
        repo = await _upsert_repo(db, payload)
        if ref != f"refs/heads/{repo.default_branch}":
            return {"status": "ignored", "reason": f"not the default branch ({ref})"}
        analysis = Analysis(
            repository_id=repo.id,
            commit_sha=payload.get("after"),
            branch=repo.default_branch,
            trigger="push",
            status=AnalysisStatus.QUEUED,
            diff_only=True,
            stats={"options": {"open_pr": True, "categories": [
                "logical_bug", "security", "performance", "architecture"
            ]}},
        )
        db.add(analysis)
        await db.flush()
        await enqueue(ANALYSIS, {"analysis_id": str(analysis.id)})
        return {"status": "queued", "analysis_id": str(analysis.id)}

    return {"status": "ignored", "event": x_github_event}
