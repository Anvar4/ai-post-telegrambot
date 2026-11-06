"""Loguru sozlamasi: sirlar maskalanadi, fayl rotatsiyasi, stdlib logging ham yo'naltiriladi."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from loguru import logger

from app.utils.security import mask_secrets

_FORMAT = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} | {message}"


class _MaskedFileSink:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handler = RotatingFileHandler(path, maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8")
        self._handler.setFormatter(logging.Formatter("%(message)s"))

    def write(self, message: str) -> None:
        record = logging.makeLogRecord({"msg": mask_secrets(str(message)).rstrip("\n"), "levelno": 20})
        self._handler.emit(record)


def _stderr_sink(message: str) -> None:
    sys.stderr.write(mask_secrets(str(message)))


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        logger.opt(depth=6, exception=record.exc_info).log(level, record.getMessage())


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    logger.remove()
    logger.add(_stderr_sink, level=level, format=_FORMAT, backtrace=False, diagnose=False)
    if log_dir is not None:
        sink = _MaskedFileSink(log_dir / "bot.log")
        logger.add(sink.write, level=level, format=_FORMAT, backtrace=False, diagnose=False)
        errors = _MaskedFileSink(log_dir / "errors.log")
        logger.add(errors.write, level="ERROR", format=_FORMAT, backtrace=False, diagnose=False)
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.INFO, force=True)
    for noisy in ("httpx", "httpcore", "httpx2", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
