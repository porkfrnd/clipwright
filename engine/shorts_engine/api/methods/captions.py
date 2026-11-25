from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from ...common.errors import EngineError
from ...common.resources import fonts_dir
from ...ingest.binaries import ffmpeg_command
from ...render.ass import build_ass, escape_filter_path, write_ass
from ...transcription.sync import estimate_offset
from ..params import CaptionPreviewParams, CaptionSyncParams
from ..registry import Registry


def register(registry: Registry) -> None:
    registry.add("captions.sync_check", CaptionSyncParams, sync_check)
    registry.add("captions.preview", CaptionPreviewParams, preview)


def _context(app, selection_id: str) -> tuple[dict, dict, dict, dict, dict]:
    selection = app.ctx.selections.get(selection_id)
    if not selection:
        raise EngineError("SELECTION_NOT_FOUND", "That clip is no longer selected in this project.")
    candidate = app.ctx.candidates.get(selection["candidateId"])
    if not candidate:
        raise EngineError("CANDIDATE_NOT_FOUND", "That clip moment no longer exists.")
    source = app.ctx.sources.get(candidate["sourceId"])
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "The source for this clip is missing.")
    run = app.ctx.runs.get(candidate["analysisRunId"])
    transcript = app.ctx.transcripts.get(run["transcriptId"]) if run and run.get("transcriptId") else None
    if not transcript:
        transcript = app.ctx.transcripts.latest_for_source(candidate["sourceId"])
    if not transcript:
        raise EngineError("TRANSCRIPT_MISSING", "Transcribe this source before checking caption sync.")
    edit = app.ctx.edits.get(selection_id)
    return selection, candidate, source, transcript, edit


async def _window_media(app, source: dict, candidate: dict, start_s: float, end_s: float) -> tuple[Path, float]:
    if source["kind"] == "file":
        path = Path(source.get("localPath") or "")
        if not path.exists():
            raise EngineError("SOURCE_MISSING", "The original file has moved. Re-import it.")
        return path, 0.0
    # Prefer an already downloaded render section that covers the window.
    for asset in app.ctx.assets.for_source(source["id"], "video_segment"):
        meta = asset.get("meta") or {}
        if meta.get("candidateId") != candidate["id"]:
            continue
        begin = float(meta.get("requestedStart", -1))
        finish = float(meta.get("requestedEnd", -1))
        if begin <= start_s and finish >= end_s and Path(asset["path"]).exists():
            return Path(asset["path"]), begin
    req_start = max(0.0, start_s - 1.0)
    req_end = min(float(source.get("durationS") or end_s + 1.0), end_s + 1.0)
    out = await app.ctx.ytdlp.download_section(
        source["url"],
        app.ctx.paths.tmp / f"sync-{app.ctx.db.new_id()[:8]}",
        start_s=req_start,
        end_s=req_end,
        max_height=720,
    )
    dest = app.ctx.paths.assets / source["id"] / f"sync-{candidate['id'][:8]}-{int(req_start * 1000)}-{int(req_end * 1000)}{out.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(out), str(dest))
    app.ctx.assets.add(
        source["id"],
        "video_segment",
        str(dest),
        start_s=req_start,
        end_s=req_end,
        bytes_=dest.stat().st_size,
        meta={"candidateId": candidate["id"], "requestedStart": req_start, "requestedEnd": req_end, "purpose": "sync"},
    )
    return dest, req_start


def _window_words(transcript: dict, start_s: float, end_s: float) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for segment in transcript.get("segments") or []:
        for word in segment.get("words") or []:
            word_start = float(word.get("startS", word.get("start_s", segment.get("startS", 0))))
            word_end = float(word.get("endS", word.get("end_s", segment.get("endS", word_start))))
            if word_end <= start_s or word_start >= end_s:
                continue
            text = str(word.get("text", "")).strip()
            if text:
                words.append({"startS": word_start, "endS": word_end, "text": text})
    words.sort(key=lambda w: w["startS"])
    return words


async def sync_check(app, params: CaptionSyncParams, secrets) -> dict[str, Any]:
    _selection, candidate, source, transcript, _edit = _context(app, params.selectionId)
    clip_start = float(candidate["startS"])
    clip_end = float(candidate["endS"])
    start = float(params.startS if params.startS is not None else clip_start)
    start = max(clip_start, min(start, max(clip_start, clip_end - 2.0)))
    end = min(clip_end, start + max(2.0, params.durationS))
    start = max(clip_start, end - params.durationS)
    media, media_offset = await _window_media(app, source, candidate, start, end)
    local_start = max(0.0, start - media_offset)
    work = app.ctx.paths.tmp / f"sync-check-{app.ctx.db.new_id()[:8]}"
    wav = await app.ctx.audio.extract_window(
        media, work / "window.wav", start_s=local_start, duration_s=end - start
    )
    words = _window_words(transcript, start, end)
    word_timing = transcript.get("wordTiming") or "approximate"
    if word_timing != "exact":
        return {
            "offsetMs": 0,
            "confidence": "Low: phrase-level timing",
            "wordsUsed": len(words),
            "wordTiming": word_timing,
            "windowStartS": start,
            "windowEndS": end,
            "checkedS": round(end - start, 2),
            "method": "This transcript has phrase-level timing, so word onsets cannot be compared reliably.",
            "disclosure": "Local estimate only. Nothing was sent to a provider.",
        }
    result = estimate_offset(wav.read_bytes(), [w["startS"] - start for w in words])
    shutil.rmtree(work, ignore_errors=True)
    return {
        **result,
        "wordTiming": word_timing,
        "windowStartS": round(start, 3),
        "windowEndS": round(end, 3),
        "checkedS": round(end - start, 2),
        "method": "Compared subtitle word onsets with local audio energy rises.",
        "disclosure": "Estimate only, computed on this device. Nothing was sent to a provider.",
    }


async def preview(app, params: CaptionPreviewParams, secrets) -> dict[str, Any]:
    _selection, candidate, source, transcript, edit = _context(app, params.selectionId)
    clip_start = float(candidate["startS"])
    clip_end = float(candidate["endS"])
    start = float(params.startS if params.startS is not None else clip_start)
    start = max(clip_start, min(start, max(clip_start, clip_end - 2.0)))
    end = min(clip_end, start + max(2.0, params.durationS))
    start = max(clip_start, end - params.durationS)
    media, media_offset = await _window_media(app, source, candidate, start, end)
    local_start = max(0.0, start - media_offset)
    style = dict(edit.get("subtitles") or {})
    style["enabled"] = True
    ass_text = build_ass(
        segments=transcript.get("segments") or [],
        start_s=start,
        end_s=end,
        style=style,
        word_timing=transcript.get("wordTiming") or "approximate",
        offset_ms=params.offsetMs,
    )
    out_dir = app.ctx.paths.tmp / "sync-previews"
    out_dir.mkdir(parents=True, exist_ok=True)
    token = f"{params.selectionId}-{int(start * 1000)}-{int(params.offsetMs)}"
    ass_path = write_ass(out_dir / f"{token}.ass", ass_text)
    output = out_dir / f"{token}.mp4"
    vf = (
        "scale=540:960:force_original_aspect_ratio=increase,"
        "crop=540:960,setsar=1,"
        f"ass={escape_filter_path(ass_path)}:fontsdir={escape_filter_path(fonts_dir())}"
    )
    args = [
        *ffmpeg_command(app.ctx.bins), "-hide_banner", "-nostdin", "-y",
        "-ss", f"{local_start:.3f}", "-t", f"{end - start:.3f}", "-i", str(media),
        "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
        str(output),
    ]
    result = await app.ctx.runner.run(args, timeout=300)
    if result.returncode != 0 or not output.exists():
        raise EngineError(
            "PREVIEW_FAILED",
            "The sync preview could not be rendered.",
            details={"ffmpeg": result.stderr[-800:]},
            retryable=True,
        )
    return {
        "path": str(output),
        "startS": round(start, 3),
        "endS": round(end, 3),
        "offsetMs": params.offsetMs,
        "disclosure": "Local preview with burned-in subtitles. Nothing was sent to a provider.",
    }
