"""RepoVue API entrypoint.

    uvicorn app.main:app --reload
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import settings
from app.db.init_db import init_db
from app.logging_config import configure_logging, get_logger
from app.worker.queue import WorkerPool
from app.worker import tasks  # noqa: F401  - registers job handlers

log = get_logger(__name__)
pool: WorkerPool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("starting", env=settings.ENV, embeddings=settings.EMBEDDING_PROVIDER)
    try:
        await init_db()
    except Exception as exc:
        log.error("db_init_failed", error=str(exc)[:300])

    global pool
    if settings.RUN_WORKER_IN_API:
        pool = WorkerPool()
        await pool.start()
        log.info("inline_worker_started", concurrency=settings.WORKER_CONCURRENCY)

    yield

    if pool is not None:
        await pool.stop()
    log.info("shutdown_complete")


app = FastAPI(
    title="RepoVue API",
    description=(
        "AI-powered codebase analysis: AST + graph indexing, LLM review, "
        "validated automatic fixes, GitHub and Jira integration."
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"]
    if not settings.is_prod
    else ["https://app.repovue.dev"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
    structlog.contextvars.bind_contextvars(request_id=request_id, path=request.url.path)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        structlog.contextvars.clear_contextvars()
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time-ms"] = str(elapsed_ms)
    if request.url.path not in ("/api/v1/health", "/metrics"):
        log.info("request", method=request.method, status=response.status_code, ms=elapsed_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    log.exception("unhandled_error", path=request.url.path)
    detail = "Internal server error" if settings.is_prod else f"{type(exc).__name__}: {exc}"
    return JSONResponse(status_code=500, content={"detail": detail})


app.include_router(api_router, prefix=settings.API_PREFIX)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "name": "RepoVue",
        "version": "1.0.0",
        "docs": "/docs",
        "api": settings.API_PREFIX,
    }
