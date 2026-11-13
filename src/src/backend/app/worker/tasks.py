"""Job handlers. Importing this module registers them."""
from __future__ import annotations

import asyncio
import uuid

from app.logging_config import configure_logging, get_logger
from app.pipeline.orchestrator import run_analysis
from app.worker.queue import WorkerPool, handler

log = get_logger(__name__)

ANALYSIS = "run_analysis"


@handler(ANALYSIS)
async def handle_analysis(payload: dict) -> None:
    await run_analysis(uuid.UUID(payload["analysis_id"]))


async def _main() -> None:
    configure_logging()
    pool = WorkerPool()
    await pool.start()
    log.info("worker_process_ready")
    try:
        await asyncio.Event().wait()  # run until SIGINT/SIGTERM
    finally:
        await pool.stop()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
