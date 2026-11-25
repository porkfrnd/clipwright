from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from typing import Any, Callable

from ..common.errors import EngineError
from ..common.paths import AppPaths
from ..common.util import content_key, sha256_file
from ..ingest.audio import AudioTools
from ..models.manager import ModelManager
from ..storage.repos import AssetRepo, SourceRepo, TranscriptRepo
from .base import TranscriptionOptions
from .subtitles import ParsedTranscript, dedupe_segments, parse_subtitle_file

Progress = Callable[[float, str], None]


def normalize_segments(parsed: ParsedTranscript) -> list[dict[str, Any]]:
    """Clamp, sort, key and serialize segments. Never rewrites spoken words."""
    segments = dedupe_segments([s for s in parsed.segments if s.text.strip()])
    segments.sort(key=lambda s: s.start_s)
    out: list[dict[str, Any]] = []
    cursor = 0.0
    for index, seg in enumerate(segments):
        start = max(cursor, seg.start_s)
        end = max(start + 0.05, seg.end_s)
        if end - start < 0.05:
            continue
        words = []
        for wi, word in enumerate(seg.words):
            w_start = max(start, min(word.start_s, end))
            w_end = max(w_start + 0.01, min(word.end_s, end))
            words.append(
                {
                    "seq": wi,
                    "start_s": round(w_start, 3),
                    "end_s": round(w_end, 3),
                    "text": word.text,
                    "confidence": word.confidence,
                }
            )
        out.append(
            {
                "seq": len(out),
                "seg_key": f"s{len(out):04d}",
                "start_s": round(start, 3),
                "end_s": round(end, 3),
                "text": seg.text,
                "words": words,
            }
        )
        cursor = start + 0.001
    return out


class TranscriptionService:
    def __init__(
        self,
        paths: AppPaths,
        audio: AudioTools,
        models: ModelManager,
        transcripts: TranscriptRepo,
        sources: SourceRepo,
        assets: AssetRepo,
    ) -> None:
        self.paths = paths
        self.audio = audio
        self.models = models
        self.transcripts = transcripts
        self.sources = sources
        self.assets = assets

    async def from_captions(
        self,
        source: dict[str, Any],
        subtitle_files: list[Path],
        *,
        progress: Progress | None = None,
        cancel: asyncio.Event | None = None,
        tmp_dir: Path | None = None,
    ) -> dict[str, Any] | None:
        if not subtitle_files:
            return None
        # Prefer a manual English subtitle, then the first manual, then auto.
        chosen = subtitle_files[0]
        for f in subtitle_files:
            if ".en" in f.name:
                chosen = f
                break
        if progress:
            progress(0.2, "Reading the captions that came with the video…")
        parsed = parse_subtitle_file(chosen)
        if not parsed.segments:
            raise EngineError("TRANSCRIPT_EMPTY", "The captions were empty, so audio transcription is needed.")
        file_hash = sha256_file(chosen)
        cache_key = content_key(
            v=1,
            kind="subtitle",
            hash=file_hash,
            parser="v2",
        )
        cached = self.transcripts.find_cached(source["id"], cache_key)
        if cached:
            if progress:
                progress(1.0, "Using the captions already on file.")
            return cached
        segments = normalize_segments(parsed)
        if not segments:
            return None
        record = self.transcripts.save(
            source["id"],
            origin="subtitle",
            engine=parsed.engine,
            model=parsed.model,
            language=parsed.language or source.get("language"),
            params={"sourceFile": chosen.name},
            cache_key=cache_key,
            word_timing=parsed.word_timing,
            segments=segments,
        )
        if progress:
            progress(1.0, "Captions are ready.")
        return record

    def prepared_audio(self, source: dict[str, Any], engine: str) -> Path | None:
        """Return audio already decoded for this source and engine, if present."""
        suffix = ".flac" if engine == "cloud_openai" else ".wav"
        for asset in self.assets.for_source(source["id"], "audio"):
            path = Path(asset.get("path") or "")
            meta = asset.get("meta") or {}
            if (
                path.suffix.lower() == suffix
                and path.exists()
                and path.stat().st_size > 0
                and (not meta.get("sourceHash") or meta.get("sourceHash") == source.get("contentHash"))
            ):
                return path
        return None

    async def transcribe(
        self,
        source: dict[str, Any],
        *,
        engine: str,
        language: str | None,
        model_name: str | None,
        progress: Progress | None = None,
        cancel: asyncio.Event | None = None,
        job_tmp: Path | None = None,
        provider: dict[str, Any] | None = None,
        api_key: str | None = None,
        media_path: Path | None = None,
    ) -> dict[str, Any]:
        if engine not in ("local_whisper", "cloud_openai"):
            raise EngineError("TRANSCRIBE_ENGINE_UNKNOWN", "Choose local or cloud transcription.")
        source_path = media_path or Path(source.get("localPath") or "")
        if not source_path.exists():
            raise EngineError("SOURCE_MISSING", "The source file is no longer on disk. Re-import it.")
        work = job_tmp or (self.paths.tmp / f"transcribe-{source['id'][:8]}")
        work.mkdir(parents=True, exist_ok=True)
        duration = float(source.get("durationS") or 0.0)

        # Reuse audio prepared by an earlier run. For URL sources this also lets
        # the job skip downloading the audio track again when only the model or
        # caption preference changed.
        expected_suffix = ".flac" if engine == "cloud_openai" else ".wav"
        audio_path: Path | None = None
        if source_path.suffix.lower() == expected_suffix and source_path.parent == self.paths.assets / source["id"]:
            audio_path = source_path
        else:
            fmt = "flac" if engine == "cloud_openai" else "wav"
            audio_path = await self.audio.extract(
                source_path, work / f"speech{expected_suffix}", fmt=fmt, cancel=cancel
            )
        if progress:
            progress(0.08, "Audio extracted.")
        audio_hash = sha256_file(audio_path)
        model_id = model_name or ("whisper-large-v3-turbo" if engine == "cloud_openai" else "small")
        cache_key = content_key(
            v=1,
            kind="audio",
            audio=audio_hash,
            engine=engine,
            model=model_id,
            language=language or "auto",
            params={"vad": True, "wordTimestamps": True},
        )
        cached = self.transcripts.find_cached(source["id"], cache_key)
        if cached:
            if progress:
                progress(1.0, "Using the transcript already on file.")
            return cached

        opts = TranscriptionOptions(language=language, word_timestamps=True)
        if engine == "local_whisper":
            model = self.models.path_for("whisper", model_id)
            if not model:
                raise EngineError(
                    "MODEL_NOT_INSTALLED",
                    "That Whisper model is not installed. Open Model Manager to download it.",
                    details={"model": model_id},
                )
            from .local_whisper import LocalWhisperEngine

            local = LocalWhisperEngine(model, model_id, ffmpeg_path=self.audio.bins.ffmpeg)
            parsed = await local.transcribe(
                audio_path, opts, duration_s=duration, progress=progress, cancel=cancel
            )
        else:
            base_url = (provider or {}).get("baseUrl") or (provider or {}).get("base_url")
            if not provider or not base_url:
                raise EngineError("PROVIDER_NOT_FOUND", "Choose a speech service provider in Settings.")
            if not api_key:
                raise EngineError(
                    "PROVIDER_KEY_MISSING",
                    "Add an API key for the speech provider in Settings.",
                )
            from .cloud_openai import CloudTranscriptionEngine

            cloud = CloudTranscriptionEngine(
                base_url=base_url,
                api_key=api_key,
                model=model_id,
                language=language,
            )
            chunks = await self.audio.chunk(
                audio_path,
                work / "chunks",
                duration_s=duration or 600.0,
                chunk_s=600.0,
                overlap_s=2.0,
                cancel=cancel,
            )
            parsed = await cloud.transcribe(
                audio_path,
                opts,
                duration_s=duration,
                progress=progress,
                cancel=cancel,
                chunks=chunks,
            )
        segments = normalize_segments(parsed)
        if not segments:
            raise EngineError(
                "TRANSCRIPT_EMPTY",
                "No speech was detected in this source. Check that it has audible speech.",
            )
        record = self.transcripts.save(
            source["id"],
            origin=parsed.origin,
            engine=parsed.engine,
            model=model_id,
            language=parsed.language or language,
            params={"vad": True, "wordTimestamps": parsed.word_timing},
            cache_key=cache_key,
            word_timing=parsed.word_timing,
            segments=segments,
        )
        # Cache the prepared audio as a reusable asset, but keep it out of the way.
        if audio_path and audio_path.exists():
            try:
                stable = self.paths.assets / source["id"] / audio_path.name
                stable.parent.mkdir(parents=True, exist_ok=True)
                if not stable.exists():
                    audio_path.replace(stable)
                self.assets.add(
                    source["id"], "audio", str(stable), bytes_=stable.stat().st_size,
                    pinned=False,
                    meta={"purpose": "transcription", "engine": engine, "sourceHash": source.get("contentHash")},
                )
            except OSError:
                pass
        if progress:
            progress(1.0, "Transcript saved.")
        return record
