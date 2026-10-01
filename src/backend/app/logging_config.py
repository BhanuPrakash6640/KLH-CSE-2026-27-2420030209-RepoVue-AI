"""JSON logs in production, human-readable colours locally."""
from __future__ import annotations

import logging
import sys

import structlog

from app.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s", stream=sys.stdout, level=settings.LOG_LEVEL.upper()
    )
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if settings.is_prod
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    for noisy in ("httpx", "urllib3", "docker"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str):
    return structlog.get_logger(name)
