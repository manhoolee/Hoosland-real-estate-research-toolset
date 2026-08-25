from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


_SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "body",
    "content",
    "cookie",
    "credentials",
    "file_content",
    "message",
    "password",
    "prompt",
    "request_body",
    "response",
    "response_body",
    "response_text",
    "secret",
    "session_secret",
    "token",
}
_SENSITIVE_SUFFIXES = (
    "_api_key",
    "_authorization",
    "_cookie",
    "_credentials",
    "_password",
    "_secret",
    "_token",
)
_MAX_STRING_LENGTH = 500
_MAX_SEQUENCE_LENGTH = 50
_MAX_MAPPING_LENGTH = 50
_MAX_DEPTH = 5


class _PrivateTimedRotatingFileHandler(TimedRotatingFileHandler):
    def _open(self):  # type: ignore[no-untyped-def]
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, 0o640)
        except OSError:
            pass
        return stream


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _is_sensitive_key(key: object) -> bool:
    normalized = str(key).strip().lower()
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_SUFFIXES)


def _safe_value(value: object, *, depth: int = 0) -> Any:
    if depth >= _MAX_DEPTH:
        return "<truncated>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STRING_LENGTH]
    if isinstance(value, Path):
        return str(value)[:_MAX_STRING_LENGTH]
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= _MAX_MAPPING_LENGTH:
                result["_truncated"] = True
                break
            safe_key = str(key)[:120]
            result[safe_key] = (
                "<redacted>"
                if _is_sensitive_key(key)
                else _safe_value(item, depth=depth + 1)
            )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        items = list(value[:_MAX_SEQUENCE_LENGTH])
        result = [_safe_value(item, depth=depth + 1) for item in items]
        if len(value) > _MAX_SEQUENCE_LENGTH:
            result.append("<truncated>")
        return result
    return type(value).__name__


class OperationLog:
    """Best-effort, private JSONL trace for product research and iteration.

    Only explicitly supplied metadata is written. A second defensive redaction
    layer strips common secret and content fields in case a caller accidentally
    passes one. The file rotates at UTC midnight and old files expire after the
    configured number of days.
    """

    def __init__(
        self,
        path: Path,
        *,
        enabled: bool = True,
        retention_days: int = 14,
    ) -> None:
        self.path = path.resolve()
        self.enabled = enabled
        self.retention_days = max(1, retention_days)
        self._lock = threading.RLock()
        self._handler: TimedRotatingFileHandler | None = None
        self._logger = logging.getLogger(f"real_estate_operation_log.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False

    @property
    def active(self) -> bool:
        return self.enabled and self._handler is not None

    def start(self) -> None:
        if not self.enabled:
            return
        with self._lock:
            if self._handler is not None:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o750)
            except OSError:
                pass
            self.path.touch(exist_ok=True)
            try:
                os.chmod(self.path, 0o640)
            except OSError:
                pass
            handler = _PrivateTimedRotatingFileHandler(
                self.path,
                when="midnight",
                interval=1,
                backupCount=self.retention_days,
                encoding="utf-8",
                utc=True,
                delay=False,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._handler = handler

    def record(self, event: str, **fields: object) -> None:
        if not self.active:
            return
        payload: dict[str, Any] = {
            "timestamp": _timestamp(),
            "schema_version": 1,
            "event": str(event)[:120],
        }
        for key, value in fields.items():
            payload[str(key)[:120]] = (
                "<redacted>" if _is_sensitive_key(key) else _safe_value(value)
            )
        self._logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    def close(self) -> None:
        with self._lock:
            handler = self._handler
            if handler is None:
                return
            self._handler = None
            self._logger.removeHandler(handler)
            handler.flush()
            handler.close()
