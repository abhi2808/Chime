"""Structured logging that cannot print tokens.

Two layers of defence: we never pass secrets to the logger, and the formatter
redacts anything that still looks like a credential.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from app.core.config import settings

_SENSITIVE_KEYS = (
    "access_token",
    "refresh_token",
    "code_verifier",
    "code_challenge",
    "client_secret",
    "authorization",
    "session_secret",
    "encryption_key",
    "token",
    "code",
)

_KEY_PATTERNS = [
    re.compile(rf"(?i)(\"?\b{key}\b\"?\s*[=:]\s*)(\"?)([^\s\",;}}&]+)\2")
    for key in _SENSITIVE_KEYS
]
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*")

REDACTED = "[redacted]"


def redact(text: str) -> str:
    text = _BEARER_PATTERN.sub(f"Bearer {REDACTED}", text)
    for pattern in _KEY_PATTERNS:
        text = pattern.sub(rf"\g<1>{REDACTED}", text)
    return text


class KeyValueFormatter(logging.Formatter):
    """`ts=... level=... logger=... msg="..." key=value` lines, redacted."""

    _RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
        "message",
        "asctime",
        "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        parts = [
            f"ts={self.formatTime(record, '%Y-%m-%dT%H:%M:%S%z')}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"msg={_quote(message)}",
        ]
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and not key.startswith("_"):
                parts.append(f"{key}={_quote(value)}")
        line = redact(" ".join(parts))
        if record.exc_info:
            line = f"{line}\n{redact(self.formatException(record.exc_info))}"
        return line


def _quote(value: Any) -> str:
    text = str(value)
    if not text:
        return '""'
    if any(char in text for char in ' "\n\t='):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return text


def configure_logging(level: str | None = None) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel((level or settings.log_level).upper())

    # Uvicorn ships its own handlers; make it use ours so nothing escapes redaction.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # httpx logs full request URLs at INFO, and auth URLs carry codes.
    logging.getLogger("httpx").setLevel("WARNING")
