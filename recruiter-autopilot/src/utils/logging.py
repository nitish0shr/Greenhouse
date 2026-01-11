"""Structured logging configuration with correlation IDs."""

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

# Context variable for correlation ID (per-request/per-task)
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
candidate_id_var: ContextVar[int | None] = ContextVar("candidate_id", default=None)
application_id_var: ContextVar[int | None] = ContextVar("application_id", default=None)


def add_context_info(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Add correlation ID and candidate context to log entries."""
    correlation_id = correlation_id_var.get()
    if correlation_id:
        event_dict["correlation_id"] = correlation_id

    candidate_id = candidate_id_var.get()
    if candidate_id:
        event_dict["candidate_id"] = candidate_id

    application_id = application_id_var.get()
    if application_id:
        event_dict["application_id"] = application_id

    return event_dict


def setup_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    """Configure structured logging for the application."""
    # Determine processors based on environment
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        add_context_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_logs:
        # Production: JSON logs for log aggregation
        shared_processors.append(structlog.processors.format_exc_info)
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        # Development: colored console output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Reduce noise from third-party libraries
    for logger_name in ["httpx", "httpcore", "asyncio", "urllib3", "celery"]:
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)


class LogContext:
    """Context manager for setting correlation and candidate context."""

    def __init__(
        self,
        correlation_id: str | None = None,
        candidate_id: int | None = None,
        application_id: int | None = None,
    ):
        self.correlation_id = correlation_id
        self.candidate_id = candidate_id
        self.application_id = application_id
        self._tokens: list = []

    def __enter__(self) -> "LogContext":
        if self.correlation_id:
            self._tokens.append(correlation_id_var.set(self.correlation_id))
        if self.candidate_id:
            self._tokens.append(candidate_id_var.set(self.candidate_id))
        if self.application_id:
            self._tokens.append(application_id_var.set(self.application_id))
        return self

    def __exit__(self, *args: Any) -> None:
        for token in reversed(self._tokens):
            # Reset to previous value
            if hasattr(token, "var"):
                token.var.reset(token)
