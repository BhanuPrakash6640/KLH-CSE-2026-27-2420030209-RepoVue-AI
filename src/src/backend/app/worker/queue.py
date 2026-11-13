"""Durable job queue on Postgres.

Neon already gives us a database, so adding Redis + Celery just to run one
background job is infrastructure you have to explain and maintain. `SELECT ...
FOR UPDATE SKIP LOCKED` gives exactly-once-ish claiming across as many worker
processes as you want, jobs survive a restart, and retries are a column.
Swap this for Celery later without touching the pipeline.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.config import settings
from app.db.models import Job, JobStatus
from app.db.session import session_scope
from app.logging_config import get_logger

log = get_logger(__name__)

HANDLERS: dict[str, callable] = {}
STALE_AFTER = timedelta(minutes=45)


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn

    return deco


async def enqueue(kind: str, payload: dict, delay_sec: int = 0) -> uuid.UUID:
    async with session_scope() as session:
        job = Job(
            kind=kind,
            payload=payload,
            run_after=datetime.now(timezone.utc) + timedelta(seconds=delay_sec),
        )
        session.add(job)
        await session.flush()
        log.info("job_enqueued", kind=kind, id=str(job.id))
        return job.id


CLAIM_SQL = text("""
UPDATE jobs SET status = 'running', locked_at = now(), attempts = attempts + 1
WHERE id = (
    SELECT id FROM jobs
    WHERE status = 'pending' AND run_after <= now()
    ORDER BY run_after
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, kind, payload, attempts, max_attempts;
""")

REAP_SQL = text("""
UPDATE jobs SET status = 'pending', locked_at = NULL
WHERE status = 'running' AND locked_at < now() - interval '45 minutes'
  AND attempts < max_attempts;
""")


async def _claim() -> dict | None:
    async with session_scope() as session:
        row = (await session.execute(CLAIM_SQL)).first()
        if row is None:
            return None
        return {
            "id": row[0], "kind": row[1], "payload": row[2],
            "attempts": row[3], "max_attempts": row[4],
        }


async def _finish(job_id: uuid.UUID, status: str, error: str | None = None, retry_in: int = 60) -> None:
    async with session_scope() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        if status == JobStatus.FAILED and job.attempts < job.max_attempts:
            job.status = JobStatus.PENDING
            job.run_after = datetime.now(timezone.utc) + timedelta(seconds=retry_in * job.attempts)
        else:
            job.status = status
        job.last_error = (error or None) and error[:2000]
        job.locked_at = None


async def _reap_stale() -> None:
    async with session_scope() as session:
        await session.execute(REAP_SQL)


async def worker_loop(worker_id: int, stop: asyncio.Event) -> None:
    log.info("worker_started", worker=worker_id)
    tick = 0
    while not stop.is_set():
        try:
            if tick % 20 == 0:
                await _reap_stale()
            tick += 1

            job = await _claim()
            if job is None:
                await asyncio.wait_for(stop.wait(), timeout=settings.WORKER_POLL_INTERVAL)
                continue

            fn = HANDLERS.get(job["kind"])
            if fn is None:
                await _finish(job["id"], JobStatus.FAILED, f"no handler for {job['kind']}")
                continue

            log.info("job_started", kind=job["kind"], id=str(job["id"]), attempt=job["attempts"])
            try:
                await fn(job["payload"])
                await _finish(job["id"], JobStatus.DONE)
                log.info("job_done", kind=job["kind"], id=str(job["id"]))
            except Exception as exc:
                log.exception("job_failed", kind=job["kind"], id=str(job["id"]))
                await _finish(job["id"], JobStatus.FAILED, f"{type(exc).__name__}: {exc}")

        except asyncio.TimeoutError:
            continue
        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("worker_loop_error")
            await asyncio.sleep(5)
    log.info("worker_stopped", worker=worker_id)


class WorkerPool:
    def __init__(self, size: int | None = None) -> None:
        self.size = size or settings.WORKER_CONCURRENCY
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self._tasks = [
            asyncio.create_task(worker_loop(i, self._stop)) for i in range(self.size)
        ]

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
