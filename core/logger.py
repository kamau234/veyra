"""Application logging.

Technical detail (SQL failures, import failures, unhandled exceptions) is
written to logs/veyra.log; the UI only ever shows human-readable messages.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from core.paths import LOG_FILE, ensure_dirs

_CONFIGURED = False
LOGGER_NAME = "veyra"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a configured logger, setting up file logging on first use."""
    global _CONFIGURED
    logger = logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
    if not _CONFIGURED:
        ensure_dirs()
        logger_root = logging.getLogger(LOGGER_NAME)
        logger_root.setLevel(logging.INFO)
        handler = RotatingFileHandler(
            LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger_root.addHandler(handler)
        logger_root.propagate = False
        _CONFIGURED = True
    return logger


def log_unexpected(logger: logging.Logger, context: str, exc: BaseException) -> str:
    """Record an unexpected exception and return a short user-facing reference."""
    reference = f"{abs(hash((context, repr(exc)))) % 10**6:06d}"
    logger.error("Unhandled error during %s (ref %s)", context, reference, exc_info=exc)
    return reference
