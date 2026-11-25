from __future__ import annotations

import logging
import re

# Patterns are deliberately conservative: redact anything that looks like a bearer
# token, a common provider key prefix, or an Authorization header value.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*[:=]\s*)(bearer\s+)?[^\s,;\"']+"),
    re.compile(r"\bgsk_[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{8,}\b"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;\"']+"),
    re.compile(r"(?i)([?&](?:key|token|api_key)=)[^&\s]+"),
]

REDACTED = "[REDACTED]"


def redact_text(value: str, secrets: list[str] | None = None) -> str:
    out = value
    for s in secrets or []:
        if s:
            out = out.replace(s, REDACTED)
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + REDACTED, out)
    return out


def redact_obj(value, secrets: list[str] | None = None):
    if isinstance(value, str):
        return redact_text(value, secrets)
    if isinstance(value, dict):
        return {k: redact_obj(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_obj(v, secrets) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_obj(v, secrets) for v in value)
    return value


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging(log_path) -> logging.Logger:
    logger = logging.getLogger("shorts_engine")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    sh = logging.StreamHandler()  # stderr only; stdout is reserved for protocol
    sh.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger
