from __future__ import annotations

import asyncio
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..common.errors import CancelledError, EngineError
from ..common.paths import AppPaths
from ..common.proc import ProcessRunner
from ..common.resources import fonts_dir
from ..common.util import format_timecode, safe_filename
from ..ingest.audio import AudioTools
from ..ingest.binaries import BinaryPaths, ffmpeg_command
from ..ingest.probe import Prober
from ..ingest.ytdlp import YtDlp
from ..storage.repos import (
    AnalysisRunRepo,
    AssetRepo,
    CandidateRepo,
    EditRepo,
    ExportJobRepo,
    SelectionRepo,
    SourceRepo,
    TranscriptRepo,
)
from .ass import build_ass, write_ass
from .encoder import EncoderChoice, EncoderProbe
from .filters import build_ffmpeg_command, parse_progress_line
from .timeline import plan_timeline, remap_segments


@dataclass
class RenderOptions:
    output_dir: Path
    quality: str = "standard"
    prefer_hardware: bool = True
    filename_template: str = "{title}-{index}-{start}"
    fps: int = 30
    min_free_bytes: int = 300 * 1024 * 1024


@dataclass
class RenderHooks:
    progress: Callable[[str, int, int, float, str], None] = lambda sid, i, n, f, m: None
    state: Callable[[str], None] = lambda state: None
    log: Callable[[str, str], None] = lambda level, message: None
    item_done: Callable[[dict[str, Any]], None] = lambda item: None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


class RenderService:
    def __init__(
        self,
        *,
        paths: AppPaths,
        bins: BinaryPaths,
        runner: ProcessRunner,
        prober: Prober,
        audio: AudioTools,
        ytdlp: YtDlp,
        encoder_probe: EncoderProbe,
        candidates: CandidateRepo,
        selections: SelectionRepo,
        edits: EditRepo,
        sources: SourceRepo,
        transcripts: TranscriptRepo,
        runs: AnalysisRunRepo,
        assets: AssetRepo,
        exports: ExportJobRepo,
    ) -> None:
        self.paths = paths
        self.bins = bins
        self.runner = runner
        self.prober = prober
        self.audio = audio
        self.ytdlp = ytdlp
        self.encoder_probe = encoder_probe
        self.candidates = candidates
        self.selections = selections
        self.edits = edits
        self.sources = sources
        self.transcripts = transcripts
        self.runs = runs
        self.assets = assets
        self.exports = exports

    async def render_batch(
        self,
        *,
        project_id: str,
        selection_ids: list[str],
        options: RenderOptions,
        hooks: RenderHooks,
        job_tmp: Path,
    ) -> dict[str, Any]:
        if not selection_ids:
            raise EngineError("NOTHING_SELECTED", "Select at least one clip to export.")
        options.output_dir.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(options.output_dir).free
        if free < options.min_free_bytes:
            raise EngineError(
                "DISK_SPACE_LOW",
                "There is not enough free disk space in the output folder. Free some space and try again.",
                details={"freeBytes": free},
            )
        encoder = await self.encoder_probe.choose(
            prefer_hardware=options.prefer_hardware, quality=options.quality
        )
        hooks.log("info", f"Encoder: {encoder.name} ({'hardware' if encoder.hardware else 'software'})")
        results: list[dict[str, Any]] = []
        total = len(selection_ids)
        for index, selection_id in enumerate(selection_ids, start=1):
            if hooks.cancel.is_set():
                break
            hooks.progress(selection_id, index, total, 0.01, f"Preparing clip {index} of {total}…")
            try:
                result = await self._render_one(
                    project_id=project_id,
                    selection_id=selection_id,
                    index=index,
                    total=total,
                    options=options,
                    encoder=encoder,
                    hooks=hooks,
                    job_tmp=job_tmp,
                )
            except CancelledError:
                raise
            except EngineError as exc:
                hooks.log("error", f"Clip {index} failed: {exc.message}")
                result = {
                    "selectionId": selection_id,
                    "ok": False,
                    "error": exc.to_dict(),
                }
                results.append(result)
                hooks.item_done(result)
                continue
            except Exception as exc:  # noqa: BLE001 - one bad clip must not corrupt the batch
                hooks.log("error", f"Clip {index} failed unexpectedly: {exc}")
                result = {
                    "selectionId": selection_id,
                    "ok": False,
                    "error": {"code": "RENDER_FAILED", "message": "This clip could not be rendered.", "details": {"error": str(exc)[:400]}, "retryable": True},
                }
                results.append(result)
                hooks.item_done(result)
                continue
            results.append(result)
            hooks.item_done(result)
        if hooks.cancel.is_set():
            raise CancelledError()
        succeeded = sum(1 for r in results if r.get("ok"))
        return {
            "itemCount": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "items": results,
            "encoder": encoder.name,
        }

    async def _render_one(
        self,
        *,
        project_id: str,
        selection_id: str,
        index: int,
        total: int,
        options: RenderOptions,
        encoder: EncoderChoice,
        hooks: RenderHooks,
        job_tmp: Path,
    ) -> dict[str, Any]:
        selection = self.selections.get(selection_id)
        if not selection:
            raise EngineError("SELECTION_NOT_FOUND", "That clip is no longer in this project.")
        candidate = self.candidates.get(selection["candidateId"])
        if not candidate:
            raise EngineError("CANDIDATE_NOT_FOUND", "That clip's source moment no longer exists.")
        source = self.sources.get(candidate["sourceId"])
        if not source:
            raise EngineError("SOURCE_NOT_FOUND", "The source for this clip is missing.")
        run = self.runs.get(candidate["analysisRunId"])
        transcript = self.transcripts.get(run["transcriptId"]) if run and run.get("transcriptId") else None
        if not transcript:
            transcript = self.transcripts.latest_for_source(candidate["sourceId"])
        if not transcript:
            raise EngineError("TRANSCRIPT_MISSING", "The transcript for this clip is missing, so subtitles cannot be built.")
        edit = self.edits.get(selection_id)
        metadata = edit.get("metadata") or {}
        title = metadata.get("title") or candidate["title"] or "clip"
        start = float(candidate["startS"])
        end = float(candidate["endS"])
        duration = max(0.2, end - start)

        media_path, media_offset, source_note = await self._prepare_media(
            source=source,
            candidate=candidate,
            job_tmp=job_tmp,
            hooks=hooks,
            start=start,
            end=end,
            index=index,
            total=total,
            selection_id=selection_id,
        )
        # Use the measured start of the downloaded section, not the requested
        # one. yt-dlp can land on an earlier keyframe; the container start time
        # tells us how far the section really begins before the requested cut.
        media_offset = await self._measured_offset(media_path, media_offset)
        local_start = start - media_offset
        if local_start < 0:
            local_start = 0

        subtitle_style = edit.get("subtitles") or {}
        ass_path: Path | None = None
        timeline: dict[str, Any] | None = None
        ass_start, ass_end = start, end
        ass_segments = transcript["segments"]
        tighten = subtitle_style.get("tighten") or {}
        if tighten.get("enabled"):
            plan = plan_timeline(
                transcript["segments"],
                start_s=start,
                end_s=end,
                pause_threshold_s=float(tighten.get("pauseThresholdS") or 0.6),
                min_pause_s=float(tighten.get("minPauseS") or 0.25),
                remove_fillers=bool(tighten.get("removeFillers")),
                word_timing=transcript.get("wordTiming") or "approximate",
            )
            if plan["supported"] and plan["cuts"]:
                duration = max(0.2, float(plan["plannedDurationS"]))
                ass_start, ass_end = 0.0, duration
                ass_segments = remap_segments(
                    transcript["segments"], start_s=start, end_s=end, cuts=plan["cuts"]
                )
                timeline = {
                    "keepRanges": [
                        {"startS": max(0.0, item["startS"] - start), "endS": max(0.0, item["endS"] - start)}
                        for item in plan["keepRanges"]
                    ],
                    "fadeS": 0.03,
                }
        if subtitle_style.get("enabled", True):
            ass_text = build_ass(
                segments=ass_segments,
                start_s=ass_start,
                end_s=ass_end,
                style=subtitle_style,
                word_timing=transcript.get("wordTiming") or "approximate",
                offset_ms=float(subtitle_style.get("offsetMs") or 0.0),
                line_offsets_ms=subtitle_style.get("lineOffsetsMs") or {},
            )
            ass_path = write_ass(job_tmp / f"clip_{index}_subtitles.ass", ass_text)

        hooks.progress(selection_id, index, total, 0.08, "Measuring audio loudness…")
        measured = await self.audio.loudness(
            media_path, start_s=local_start, duration_s=duration, cancel=hooks.cancel
        )

        final_path = self._output_path(options, title, index, start, source)
        export_id = self.exports.create(project_id, selection_id, str(final_path), edit)
        temp_output = job_tmp / f"render_{index}.mp4"
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        probe = await self.prober.probe(media_path)
        music_path = (edit.get("audio") or {}).get("musicPath")

        cmd = build_ffmpeg_command(
            ffmpeg=ffmpeg_command(self.bins),
            source=media_path,
            start_s=local_start,
            duration=duration,
            output=temp_output,
            encoder_args=encoder.args,
            has_audio=bool(probe.get("has_audio")),
            music_path=Path(music_path) if music_path else None,
            framing=edit.get("framing") or {},
            subtitles=subtitle_style,
            effects=edit.get("effects") or {},
            audio=edit.get("audio") or {},
            ass_path=ass_path,
            fonts_dir=fonts_dir(),
            measured=measured,
            source_fps=probe.get("fps"),
            timeline=timeline,
        )
        hooks.progress(selection_id, index, total, 0.12, f"Rendering clip {index} of {total}…")

        def on_line(line: str) -> None:
            fraction = parse_progress_line(line, duration)
            if fraction is not None:
                hooks.progress(
                    selection_id, index, total, 0.12 + 0.85 * fraction, f"Rendering clip {index} of {total}…"
                )

        result = await self.runner.run(
            cmd,
            cancel=hooks.cancel,
            timeout=3600,
            on_line=on_line,
        )
        if result.returncode != 0 or not temp_output.exists():
            self.exports.finish(export_id, state="failed", error="Render failed")
            hooks.log("error", (result.stderr or "")[-800:])
            raise EngineError(
                "RENDER_FAILED",
                "This clip could not be rendered. Details are in the error log.",
                details={"ffmpeg": (result.stderr or "")[-800:]},
                retryable=True,
            )
        hooks.progress(selection_id, index, total, 0.97, "Checking the exported file…")
        report = await self._validate_output(temp_output, duration)
        if not report["ok"]:
            self.exports.finish(export_id, state="failed", error=report["reason"], ffprobe=report)
            temp_output.unlink(missing_ok=True)
            raise EngineError(
                "EXPORT_VALIDATION_FAILED",
                f"The render finished but failed validation: {report['reason']}",
                details=report,
                retryable=True,
            )
        final_path.parent.mkdir(parents=True, exist_ok=True)
        part = final_path.with_suffix(final_path.suffix + ".part")
        shutil.copyfile(temp_output, part)
        os.replace(part, final_path)
        temp_output.unlink(missing_ok=True)
        self.exports.finish(export_id, state="succeeded", ffprobe=report)
        hooks.progress(selection_id, index, total, 1.0, f"Clip {index} exported.")
        return {
            "selectionId": selection_id,
            "exportId": export_id,
            "ok": True,
            "outputPath": str(final_path),
            "bytes": final_path.stat().st_size,
            "encoder": encoder.name,
            "ffprobe": report,
            "sourceNote": source_note,
        }

    async def _measured_offset(self, media_path: Path, requested_start: float) -> float:
        """Return the source time represented by media time zero.

        The probe's ``start_time`` is the container's first timestamp. A section
        trimmed on a keyframe can carry a small positive offset; adding it to the
        requested start keeps subtitles and audio on the same timeline.
        """
        try:
            info = await self.prober.probe(media_path, fresh=True)
        except EngineError:
            return requested_start
        start_time = float(info.get("start_time_s") or 0.0)
        return max(0.0, requested_start + start_time)

    async def _prepare_media(
        self,
        *,
        source: dict[str, Any],
        candidate: dict[str, Any],
        job_tmp: Path,
        hooks: RenderHooks,
        start: float,
        end: float,
        index: int,
        total: int,
        selection_id: str,
    ) -> tuple[Path, float, str | None]:
        if source["kind"] == "file":
            path = Path(source.get("localPath") or "")
            if not path.exists():
                raise EngineError("SOURCE_MISSING", "The original file has moved. Re-import it.")
            return path, 0.0, None
        if not source.get("url"):
            raise EngineError("SOURCE_MISSING", "This source has no file and no URL to download from.")
        pad = 3.0
        req_start = max(0.0, start - pad)
        req_end = min(float(source.get("durationS") or end + pad), end + pad)
        cached = [
            a for a in self.assets.for_source(source["id"], "video_segment")
            if a.get("meta", {}).get("candidateId") == candidate["id"]
            and abs(float(a.get("meta", {}).get("requestedStart", -1)) - req_start) < 0.05
            and abs(float(a.get("meta", {}).get("requestedEnd", -1)) - req_end) < 0.05
            and Path(a["path"]).exists()
        ]
        if cached:
            asset = cached[0]
            return Path(asset["path"]), float(asset["meta"].get("requestedStart", 0.0)), "Reused a previously downloaded section."
        hooks.progress(selection_id, index, total, 0.03, "Downloading just the needed video section…")
        section = await self.ytdlp.download_section(
            source["url"],
            job_tmp / f"section_{index}",
            start_s=req_start,
            end_s=req_end,
            max_height=1080,
            cancel=hooks.cancel,
        )
        # Keep downloaded sections in the asset store, not the job temp dir, so
        # a second export does not hit YouTube again. The key includes the exact
        # padded range, so a boundary edit cannot silently reuse the old section.
        dest = (
            self.paths.assets / source["id"]
            / f"segment-{candidate['id'][:8]}-{int(req_start * 1000)}-{int(req_end * 1000)}{section.suffix}"
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            section.unlink(missing_ok=True)
        else:
            shutil.move(str(section), str(dest))
        self.assets.add(
            source["id"],
            "video_segment",
            str(dest),
            start_s=req_start,
            end_s=req_end,
            bytes_=dest.stat().st_size,
            meta={"candidateId": candidate["id"], "requestedStart": req_start, "requestedEnd": req_end},
        )
        return dest, req_start, "Downloaded a padded section; exact start depends on the site's keyframes."

    async def _validate_output(self, path: Path, expected_duration: float) -> dict[str, Any]:
        try:
            info = await self.prober.probe(path)
        except EngineError as exc:
            return {"ok": False, "reason": exc.message}
        issues = []
        if info.get("video_codec") != "h264":
            issues.append(f"codec {info.get('video_codec')}")
        if info.get("width") != 1080 or info.get("height") != 1920:
            issues.append(f"resolution {info.get('width')}x{info.get('height')}")
        if not info.get("has_audio"):
            issues.append("missing audio")
        if abs(float(info.get("duration_s") or 0) - expected_duration) > max(1.0, expected_duration * 0.05):
            issues.append(f"duration {info.get('duration_s')}s")
        ok = not issues
        return {
            "ok": ok,
            "reason": "All checks passed." if ok else ", ".join(issues),
            "codec": info.get("video_codec"),
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "durationS": info.get("duration_s"),
            "hasAudio": info.get("has_audio"),
            "audioCodec": info.get("audio_codec"),
            "format": info.get("format_name"),
        }

    def _output_path(self, options: RenderOptions, title: str, index: int, start: float, source: dict[str, Any]) -> Path:
        values = {
            "title": title,
            "index": str(index),
            "start": format_timecode(start, ms=False).replace(":", ""),
            "source": source.get("title") or "source",
        }
        name = options.filename_template
        for key, value in values.items():
            name = name.replace("{" + key + "}", value)
        name = safe_filename(name, fallback=f"clip-{index}")
        base = options.output_dir / f"{name}.mp4"
        if not base.exists():
            return base
        counter = 2
        while True:
            candidate = options.output_dir / f"{name} ({counter}).mp4"
            if not candidate.exists():
                return candidate
            counter += 1
