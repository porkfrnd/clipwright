from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ..common.errors import EngineError
from ..common.proc import ProcessRunner
from .binaries import BinaryPaths, ffprobe_command


def _fraction(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            return float(num) / float(den) if float(den) else None
        return float(value)
    except (ValueError, ZeroDivisionError):
        return None


def parse_probe(data: dict[str, Any]) -> dict[str, Any]:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = None
    for candidate in (fmt.get("duration"), (video or {}).get("duration"), (audio or {}).get("duration")):
        try:
            if candidate not in (None, "N/A"):
                duration = float(candidate)
                break
        except (TypeError, ValueError):
            continue
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise EngineError("MEDIA_INVALID", "This file has no readable duration and cannot be imported.")
    fps = None
    if video:
        fps = _fraction(video.get("avg_frame_rate")) or _fraction(video.get("r_frame_rate"))
    language = None
    for stream in (audio, video):
        if stream and stream.get("tags", {}).get("language"):
            language = stream["tags"]["language"]
            break
    if fmt.get("tags", {}).get("language"):
        language = fmt["tags"]["language"]
    return {
        "duration_s": round(duration, 3),
        "width": int(video["width"]) if video and video.get("width") else None,
        "height": int(video["height"]) if video and video.get("height") else None,
        "fps": round(fps, 3) if fps else None,
        "has_video": video is not None,
        "has_audio": audio is not None,
        "video_codec": video.get("codec_name") if video else None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "language": language,
        "format_name": fmt.get("format_name"),
        "size_bytes": int(fmt["size"]) if fmt.get("size") else None,
        "title": (fmt.get("tags") or {}).get("title"),
        "streams": [
            {
                "type": s.get("codec_type"),
                "codec": s.get("codec_name"),
                "width": s.get("width"),
                "height": s.get("height"),
                "channels": s.get("channels"),
                "sample_rate": s.get("sample_rate"),
            }
            for s in streams
        ],
        "raw": data,
    }


class Prober:
    def __init__(self, bins: BinaryPaths, runner: ProcessRunner) -> None:
        self.bins = bins
        self.runner = runner
        self._cache: dict[tuple[str, int, int], dict[str, Any]] = {}

    async def probe(self, path: Path, *, fresh: bool = False) -> dict[str, Any]:
        if not path.exists() or path.stat().st_size == 0:
            raise EngineError("MEDIA_INVALID", "That file is empty or missing.")
        stat = path.stat()
        key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
        if not fresh and key in self._cache:
            return self._cache[key]
        result = await self.runner.run(
            [
                *ffprobe_command(self.bins),
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            timeout=60,
        )
        if result.returncode != 0:
            raise EngineError(
                "MEDIA_INVALID",
                "That file could not be read as video or audio. Choose a different file.",
                details={"probe": result.stderr[-800:]},
            )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise EngineError("MEDIA_INVALID", "The media probe returned unreadable data.") from exc
        info = parse_probe(data)
        if not info["has_video"]:
            raise EngineError(
                "MEDIA_NO_VIDEO",
                "That file has audio but no video. Import a video file to make Shorts.",
            )
        if info["duration_s"] > 6 * 3600:
            raise EngineError(
                "MEDIA_TOO_LONG",
                "This source is longer than 6 hours. Trim it first or import a shorter file.",
            )
        self._cache[key] = info
        return info
