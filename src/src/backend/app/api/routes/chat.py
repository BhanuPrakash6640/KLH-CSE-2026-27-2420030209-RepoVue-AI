from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DB, Auth
from app.schemas.api import ChatRequest, ChatResponse
from app.services.chat import answer_finding_query

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat_findings(payload: ChatRequest, db: DB, _: Auth):
    """Conversational code doctor / findings assistant. Explains any defect,
    root cause, security vulnerability, or performance issue according to the
    evidence and findings of the repository analysis."""
    return await answer_finding_query(db, payload)
