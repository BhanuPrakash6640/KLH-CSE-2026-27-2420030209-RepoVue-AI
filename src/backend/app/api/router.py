from fastapi import APIRouter

from app.api.routes import analyses, chat, findings, health, webhooks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(analyses.router)
api_router.include_router(findings.router)
api_router.include_router(chat.router)
api_router.include_router(webhooks.router)
