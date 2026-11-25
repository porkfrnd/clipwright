from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .subtitles import ParsedTranscript


@dataclass
class TranscriptionOptions:
    language: str | None = None
    word_timestamps: bool = True


class TranscriptionEngine(Protocol):
    name: str
    model: str

    async def transcribe(
        self,
        audio_path: Path,
        opts: TranscriptionOptions,
        *,
        duration_s: float | None = None,
        progress: Callable[[float, str], None] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> ParsedTranscript: ...


Progress = Callable[[float, str], None]


def _emit(progress: Progress | None, fraction: float, message: str) -> None:
    if progress:
        progress(max(0.0, min(1.0, fraction)), message)
