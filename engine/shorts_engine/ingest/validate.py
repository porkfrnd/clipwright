from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from ..common.errors import EngineError


def validate_source_url(url: str) -> str:
    if not isinstance(url, str):
        raise EngineError("URL_INVALID", "Paste a link that starts with http:// or https://.")
    value = url.strip()
    if not value:
        raise EngineError("URL_INVALID", "Paste a link that starts with http:// or https://.")
    if any(ch.isspace() for ch in value):
        raise EngineError("URL_INVALID", "Links cannot contain spaces.")
    if value.startswith("-"):
        raise EngineError("URL_INVALID", "That does not look like a link.")
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise EngineError("URL_INVALID", "Only http:// and https:// links are supported.")
    host = parsed.hostname or ""
    if not host or ("." not in host and host != "localhost" and ":" not in host):
        raise EngineError("URL_INVALID", "That link has no usable host.")
    if len(value) > 2048:
        raise EngineError("URL_INVALID", "That link is too long.")
    return value


def sanitize_subtitle_lang(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "", value)[:20]


def clear_partial_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
