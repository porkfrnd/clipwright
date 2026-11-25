from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..common.errors import EngineError
from ..common.proc import ProcessRunner
from .binaries import BinaryPaths, ffmpeg_command


class AudioTools:
    def __init__(self, bins: BinaryPaths, runner: ProcessRunner) -> None:
        self.bins = bins
        self.runner = runner

    async def extract(
        self,
        source: Path,
        out_path: Path,
        *,
        fmt: str = "flac",
        cancel=None,
    ) -> Path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        codec = ["-c:a", "flac", "-compression_level", "5"] if fmt == "flac" else ["-c:a", "pcm_s16le"]
        args = [
            *ffmpeg_command(self.bins), "-hide_banner", "-nostdin", "-y",
            "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", *codec, str(out_path),
        ]
        result = await self.runner.run(args, cancel=cancel, timeout=1800)
        if result.returncode != 0 or not out_path.exists():
            raise EngineError(
                "AUDIO_EXTRACT_FAILED",
                "The audio track could not be extracted from this source.",
                details={"ffmpeg": result.stderr[-1000:]},
            )
        return out_path

    async def chunk(
        self,
        audio: Path,
        out_dir: Path,
        *,
        duration_s: float,
        chunk_s: float = 600.0,
        overlap_s: float = 2.0,
        cancel=None,
    ) -> list[dict[str, Any]]:
        """Split audio into overlapping chunks. Offsets are in source time."""
        out_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[dict[str, Any]] = []
        start = 0.0
        index = 0
        suffix = audio.suffix or ".flac"
        while start < duration_s:
            end = min(duration_s, start + chunk_s)
            out = out_dir / f"chunk_{index:04d}{suffix}"
            args = [
                *ffmpeg_command(self.bins), "-hide_banner", "-nostdin", "-y",
                "-ss", f"{start:.3f}", "-t", f"{max(0.1, end - start):.3f}",
                "-i", str(audio), "-vn", "-ac", "1", "-ar", "16000",
                *(["-c:a", "flac"] if suffix == ".flac" else ["-c:a", "pcm_s16le"]),
                str(out),
            ]
            result = await self.runner.run(args, cancel=cancel, timeout=900)
            if result.returncode != 0:
                raise EngineError("AUDIO_CHUNK_FAILED", "Audio could not be prepared for transcription.")
            chunks.append({"path": str(out), "start_s": start, "end_s": end, "index": index})
            if end >= duration_s:
                break
            start = max(0.0, end - overlap_s)
            index += 1
        return chunks

    async def silences(
        self,
        audio_or_video: Path,
        *,
        noise_db: float = -35.0,
        min_duration_s: float = 0.35,
        cancel=None,
    ) -> list[tuple[float, float]]:
        args = [
            *ffmpeg_command(self.bins), "-hide_banner", "-nostdin",
            "-i", str(audio_or_video), "-af", f"silencedetect=noise={noise_db}dB:d={min_duration_s}",
            "-f", "null", "-",
        ]
        result = await self.runner.run(args, cancel=cancel, timeout=1800)
        # silencedetect writes to stderr; returncode is still 0.
        starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", result.stderr)]
        ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", result.stderr)]
        return [(s, e) for s, e in zip(starts, ends)]

    async def loudness(
        self, media: Path, *, start_s: float = 0.0, duration_s: float | None = None, cancel=None
    ) -> dict[str, float]:
        args = [*ffmpeg_command(self.bins), "-hide_banner", "-nostdin"]
        if start_s > 0:
            args += ["-ss", f"{start_s:.3f}"]
        if duration_s:
            args += ["-t", f"{duration_s:.3f}"]
        args += [
            "-i", str(media),
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-",
        ]
        result = await self.runner.run(args, cancel=cancel, timeout=900)
        match = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr, re.S)
        if not match:
            return {}
        import json

        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
        out: dict[str, float] = {}
        for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
            try:
                out[key] = float(data[key])
            except (KeyError, ValueError):
                pass
        return out
