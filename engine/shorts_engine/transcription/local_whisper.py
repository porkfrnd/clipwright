from __future__ import annotations

import asyncio
import gc
import subprocess
from pathlib import Path

from ..common.errors import CancelledError, EngineError
from .base import Progress, TranscriptionOptions, _emit
from .subtitles import ParsedTranscript, Segment, Word


class LocalWhisperEngine:
    name = "local_whisper"

    def __init__(
        self,
        model_path: Path,
        model_name: str,
        *,
        device: str = "cpu",
        compute_type: str = "int8",
        cpu_threads: int = 0,
        ffmpeg_path: str | None = None,
    ) -> None:
        self.model_path = model_path
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.ffmpeg_path = ffmpeg_path

    def _load(self):
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise EngineError(
                "TRANSCRIBER_UNAVAILABLE",
                "Local transcription is not available in this build. Use cloud transcription or reinstall.",
            ) from exc
        try:
            if self.cpu_threads:
                return WhisperModel(
                    str(self.model_path),
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=self.cpu_threads,
                )
            return WhisperModel(str(self.model_path), device=self.device, compute_type=self.compute_type)
        except Exception as exc:
            raise EngineError(
                "MODEL_LOAD_FAILED",
                "The local Whisper model could not be loaded. Try reinstalling the model in the Model Manager.",
                details={"error": str(exc)[:400]},
            ) from exc

    async def transcribe(
        self,
        audio_path: Path,
        opts: TranscriptionOptions,
        *,
        duration_s: float | None = None,
        progress: Progress | None = None,
        cancel: asyncio.Event | None = None,
    ) -> ParsedTranscript:
        loop = asyncio.get_running_loop()

        def thread_progress(fraction: float, message: str) -> None:
            loop.call_soon_threadsafe(_emit, progress, fraction, message)

        return await asyncio.to_thread(
            self._transcribe_sync, audio_path, opts, duration_s, thread_progress, cancel
        )

    def _decode_audio(self, audio_path: Path):
        """Decode with the bundled ffmpeg into a float32 mono array.

        This avoids depending on PyAV's shifting decode API inside faster-whisper.
        numpy is imported here so the engine can answer Home/Settings requests
        without loading the scientific stack at process startup.
        """
        import numpy as np
        ffmpeg = self.ffmpeg_path
        if not ffmpeg:
            raise EngineError("FFMPEG_MISSING", "FFmpeg is required for local transcription.")
        result = subprocess.run(
            [ffmpeg, "-v", "error", "-nostdin", "-i", str(audio_path),
             "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
            capture_output=True,
            timeout=1800,
        )
        if result.returncode != 0:
            raise EngineError(
                "AUDIO_DECODE_FAILED",
                "The extracted audio could not be decoded for local transcription.",
                details={"ffmpeg": result.stderr.decode("utf-8", "replace")[-600:]},
            )
        audio = np.frombuffer(result.stdout, dtype=np.float32)
        if audio.size == 0:
            raise EngineError("TRANSCRIPT_EMPTY", "The audio track decoded to silence.")
        return audio

    def _transcribe_sync(
        self,
        audio_path: Path,
        opts: TranscriptionOptions,
        duration_s: float | None,
        progress: Progress | None,
        cancel: asyncio.Event | None,
    ) -> ParsedTranscript:
        if cancel and cancel.is_set():
            raise CancelledError()
        _emit(progress, 0.02, "Loading the local speech model…")
        audio = self._decode_audio(audio_path)
        model = self._load()
        try:
            _emit(progress, 0.08, "Listening to the audio…")
            segments_iter, info = model.transcribe(
                audio,
                language=opts.language,
                word_timestamps=opts.word_timestamps,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                # Greedy decoding is materially faster on CPU (626 s of real
                # speech: 40.4 s vs 66.8 s with beam 5) and keeps the same
                # word timestamps. Captions are the preferred path when present.
                beam_size=1,
                condition_on_previous_text=False,
            )
            total = duration_s or getattr(info, "duration", None) or 0.0
            parsed: list[Segment] = []
            last_end = 0.0
            for seg in segments_iter:
                if cancel and cancel.is_set():
                    raise CancelledError()
                words = [
                    Word(
                        start_s=float(w.start),
                        end_s=float(w.end),
                        text=str(w.word).strip(),
                        confidence=float(w.probability) if w.probability is not None else None,
                    )
                    for w in (seg.words or [])
                    if str(w.word).strip()
                ]
                text = (seg.text or "").strip()
                if text:
                    parsed.append(Segment(float(seg.start), float(seg.end), text, words))
                last_end = float(seg.end)
                if total:
                    _emit(progress, 0.08 + 0.9 * min(1.0, last_end / total), "Transcribing…")
            language = getattr(info, "language", None) or opts.language
            _emit(progress, 1.0, "Transcript ready.")
            return ParsedTranscript(
                language=language,
                word_timing="exact" if any(s.words for s in parsed) else "none",
                segments=parsed,
                origin="local_whisper",
                engine="faster-whisper",
                model=self.model_name,
            )
        finally:
            # Release the model and its memory immediately after the run.
            del model
            gc.collect()
