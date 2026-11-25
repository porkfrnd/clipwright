from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            data = fh.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def content_key(**parts: Any) -> str:
    payload = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def estimate_tokens(text: str) -> int:
    """Tokenizer-free approximation. ~4 chars/token plus a margin."""
    return max(1, math.ceil(len(text) / 3.6))


def format_timecode(seconds: float, *, ms: bool = True) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    if ms:
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    return f"{h:02d}:{m:02d}:{int(s):02d}"


def safe_filename(name: str, fallback: str = "clip") -> str:
    cleaned = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    cleaned = cleaned[:120]
    return cleaned or fallback
