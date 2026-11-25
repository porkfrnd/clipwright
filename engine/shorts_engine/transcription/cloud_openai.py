from __future__ import annotations

import asyncio
import time
from pathlib import Path

import httpx

from ..ai.ratelimit import parse_rate_limit_headers
from ..common.errors import CancelledError, EngineError, RateLimited
from .base import Progress, TranscriptionOptions, _emit
from .subtitles import ParsedTranscript, Segment, Word, dedupe_segments, parse_verbose_json


class CloudTranscriptionEngine:
    name = "cloud_openai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        language: str | None = None,
        request_timeout: float = 300.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.language = language
        self.request_timeout = request_timeout
        self.max_retries = max_retries
        self.last_rate_headers = None

    async def transcribe(
        self,
        audio_path: Path,
        opts: TranscriptionOptions,
        *,
        duration_s: float | None = None,
        progress: Progress | None = None,
        cancel: asyncio.Event | None = None,
        chunks: list[dict] | None = None,
    ) -> ParsedTranscript:
        """Transcribe one file, or a prepared list of chunks (chunk dicts carry start_s)."""
        chunk_list = chunks or [{"path": str(audio_path), "start_s": 0.0, "end_s": duration_s or 0.0}]
        merged: list[Segment] = []
        language = opts.language or self.language
        word_timing = "none"
        prev_end = 0.0
        for index, chunk in enumerate(chunk_list):
            if cancel and cancel.is_set():
                raise CancelledError()
            _emit(
                progress,
                0.03 + 0.9 * index / max(1, len(chunk_list)),
                f"Uploading audio chunk {index + 1} of {len(chunk_list)}…",
            )
            data = await self._transcribe_chunk(Path(chunk["path"]), language, opts.word_timestamps, cancel)
            parsed = parse_verbose_json(data, language=language)
            offset = float(chunk.get("start_s", 0.0))
            for seg in parsed.segments:
                seg.start_s += offset
                seg.end_s += offset
                for word in seg.words:
                    word.start_s += offset
                    word.end_s += offset
                # Overlap handling: drop content wholly inside the previous chunk.
                if seg.end_s <= prev_end + 0.05:
                    continue
                if seg.start_s < prev_end:
                    seg.start_s = prev_end + 0.05
                    seg.words = [w for w in seg.words if w.end_s > seg.start_s]
                    if not seg.words:
                        continue
                merged.append(seg)
                prev_end = max(prev_end, seg.end_s)
            if parsed.word_timing == "exact":
                word_timing = "exact"
            elif word_timing == "none":
                word_timing = parsed.word_timing
            language = parsed.language or language
            _emit(
                progress,
                0.03 + 0.9 * (index + 1) / max(1, len(chunk_list)),
                f"Transcribed chunk {index + 1} of {len(chunk_list)}.",
            )
        merged = dedupe_segments(merged)
        _emit(progress, 1.0, "Transcript ready.")
        return ParsedTranscript(
            language=language,
            word_timing=word_timing,
            segments=merged,
            origin="cloud",
            engine="openai-compatible",
            model=self.model,
        )

    async def _transcribe_chunk(
        self,
        path: Path,
        language: str | None,
        want_words: bool,
        cancel: asyncio.Event | None,
    ) -> dict:
        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        attempt = 0
        include_granularity = want_words
        while True:
            if cancel and cancel.is_set():
                raise CancelledError()
            form = {
                "model": self.model,
                "response_format": "verbose_json",
                "temperature": "0",
            }
            if language:
                form["language"] = language
            if include_granularity:
                form["timestamp_granularities[]"] = "word"
            try:
                with path.open("rb") as fh:
                    files = {"file": (path.name, fh, "audio/flac" if path.suffix == ".flac" else "audio/wav")}
                    async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                        response = await client.post(url, headers=headers, data=form, files=files)
            except httpx.TimeoutException as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(2**attempt)
                    continue
                raise EngineError(
                    "TRANSCRIBE_TIMEOUT",
                    "The speech service did not answer in time. Try again or use local transcription.",
                    retryable=True,
                ) from exc
            except httpx.RequestError as exc:
                if attempt < self.max_retries:
                    attempt += 1
                    await asyncio.sleep(2**attempt)
                    continue
                raise EngineError(
                    "TRANSCRIBE_NETWORK",
                    "The speech service could not be reached. Check your connection.",
                    retryable=True,
                ) from exc

            self.last_rate_headers = parse_rate_limit_headers(response.headers)
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise EngineError("TRANSCRIBE_BAD_RESPONSE", "The speech service returned unreadable data.") from exc
            if response.status_code == 400 and include_granularity:
                body = response.text.lower()
                if "timestamp" in body or "granular" in body or "unknown" in body:
                    include_granularity = False
                    continue
            if response.status_code in (401, 403):
                raise EngineError(
                    "PROVIDER_AUTH_FAILED",
                    "The speech service rejected the API key. Check the key in Settings.",
                )
            if response.status_code == 413:
                raise EngineError(
                    "AUDIO_TOO_LARGE",
                    "This audio chunk is too large for the speech service. Try a smaller chunk size.",
                )
            if response.status_code == 429:
                retry = self.last_rate_headers.retry_after_s or 5.0
                if attempt >= self.max_retries:
                    raise RateLimited(retry, "The speech service is rate limiting this key.")
                attempt += 1
                await asyncio.sleep(min(retry, 120))
                continue
            if response.status_code >= 500 and attempt < self.max_retries:
                attempt += 1
                await asyncio.sleep(2**attempt)
                continue
            raise EngineError(
                "TRANSCRIBE_FAILED",
                "The speech service could not transcribe this audio.",
                details={"status": response.status_code, "body": response.text[:500]},
                retryable=response.status_code >= 500,
            )
