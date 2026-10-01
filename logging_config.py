"""Small, privacy-conscious application logging setup."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from app_paths import LOGS_DIRECTORY

LOG_DIRECTORY = LOGS_DIRECTORY
LOG_FILE = LOG_DIRECTORY / "yt-livestream-chatbot.log"
LOGGER_NAME = "yt_livestream_chatbot"


def configure_logging() -> logging.Logger:
    """Configure a bounded file log once per process without touching root logging."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Diagnostics are helpful, but a read-only install folder must not stop
        # the runtime service from entering its temporary-memory fallback.
        logger.addHandler(logging.NullHandler())
        return logger

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    """Write compact metadata only; callers must never supply user content or secrets."""
    serialized_fields = " ".join(
        f"{key}={_format_value(value)}" for key, value in fields.items()
    )
    logger.info("%s%s", event, f" {serialized_fields}" if serialized_fields else "")


def _format_value(value: object) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value).replace(" ", "_")[:120]
