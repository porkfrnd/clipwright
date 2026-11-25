from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..common.proc import ProcessRunner
from ..ingest.binaries import BinaryPaths, ffmpeg_command


@dataclass
class EncoderChoice:
    name: str
    args: list[str]
    hardware: bool
    note: str = ""


LIBX264 = EncoderChoice(
    name="libx264",
    args=["-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-profile:v", "high", "-level", "4.1"],
    hardware=False,
    note="Software H.264 encoder. Works everywhere.",
)

CANDIDATE_ENCODERS = [
    EncoderChoice(
        name="h264_nvenc",
        args=["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "19", "-b:v", "0", "-profile:v", "high"],
        hardware=True,
        note="NVIDIA hardware encoder.",
    ),
    EncoderChoice(
        name="h264_qsv",
        args=["-c:v", "h264_qsv", "-preset", "veryfast", "-global_quality", "20"],
        hardware=True,
        note="Intel Quick Sync hardware encoder.",
    ),
    EncoderChoice(
        name="h264_amf",
        args=["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20"],
        hardware=True,
        note="AMD hardware encoder.",
    ),
    EncoderChoice(
        name="h264_videotoolbox",
        args=["-c:v", "h264_videotoolbox", "-b:v", "12M", "-profile:v", "high"],
        hardware=True,
        note="Apple VideoToolbox hardware encoder.",
    ),
]


class EncoderProbe:
    def __init__(self, bins: BinaryPaths, runner: ProcessRunner) -> None:
        self.bins = bins
        self.runner = runner
        self._cache: list[dict[str, Any]] | None = None

    async def available(self) -> list[dict[str, Any]]:
        if self._cache is not None:
            return self._cache
        results: list[dict[str, Any]] = []
        ffmpeg = ffmpeg_command(self.bins)
        for choice in CANDIDATE_ENCODERS:
            args = [
                *ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.4:r=30",
                "-an", *choice.args, "-f", "null", "-",
            ]
            try:
                result = await self.runner.run(args, timeout=30)
                ok = result.returncode == 0
                note = result.stderr.strip().splitlines()[-1][:200] if not ok and result.stderr else choice.note
            except Exception as exc:
                ok, note = False, str(exc)[:200]
            results.append(
                {
                    "name": choice.name,
                    "hardware": True,
                    "ok": ok,
                    "note": note,
                    "args": choice.args,
                }
            )
            if ok and choice.name == "h264_nvenc":
                # NVENC is the strongest option; still probe the others for reporting.
                pass
        self._cache = results
        return results

    async def choose(self, *, prefer_hardware: bool = True, quality: str = "standard") -> EncoderChoice:
        if prefer_hardware:
            for entry in await self.available():
                if entry["ok"]:
                    for choice in CANDIDATE_ENCODERS:
                        if choice.name == entry["name"]:
                            if quality == "high" and choice.name == "h264_nvenc":
                                return EncoderChoice(
                                    name=choice.name,
                                    args=["-c:v", "h264_nvenc", "-preset", "p7", "-cq", "17", "-b:v", "0", "-profile:v", "high"],
                                    hardware=True,
                                    note=choice.note,
                                )
                            return choice
        if quality == "high":
            return EncoderChoice(
                name="libx264",
                args=["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-level", "4.1"],
                hardware=False,
                note="Software H.264 encoder, slower and higher quality.",
            )
        return LIBX264
