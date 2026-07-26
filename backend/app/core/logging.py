"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import sys

import structlog

_CONFIGURED = False


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging once per process."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    _CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    configure_logging()
    return structlog.get_logger(name)
