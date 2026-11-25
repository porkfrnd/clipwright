from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ..ai.adapter import AdapterHooks
from ..common.errors import EngineError
from ..discovery.pipeline import AnalysisHooks, AnalysisOptions, DiscoveryPipeline
from ..render.service import RenderHooks, RenderOptions
from ..storage.repos import decamelize
from .methods.providers import make_adapter, resolve_key

CAPTION_SUFFIXES = (".vtt", ".srt")


def register_jobs(app) -> None:
    app.ctx.job_manager.register("analysis", analysis_job)
    app.ctx.job_manager.register("transcription", transcription_job)
    app.ctx.job_manager.register("render", render_job)
    app.ctx.job_manager.register("model_download", model_download_job)


def _request_logger(ctx):
    if not ctx.settings.get("privacy", {}).get("requestLogEnabled", True):
        return None

    def log(provider: str, model: str | None, operation: str, tokens: int, categories: list[str], outcome: str) -> None:
        ctx.request_log.add(provider, model, operation, tokens, categories, outcome)

    return log


async def analysis_job(job, params: dict[str, Any]) -> dict[str, Any]:
    source = app_source(job, params["sourceId"])
    transcript = job.ctx.transcripts.get(params["transcriptId"])
    if not transcript:
        raise EngineError("TRANSCRIPT_NOT_FOUND", "The transcript for this analysis is missing.")
    profile = job.ctx.providers.get(params.get("providerProfileId") or "")
    if not profile:
        raise EngineError("PROVIDER_NOT_FOUND", "The AI provider for this analysis no longer exists.")
    key = resolve_key(profile, job.secrets)
    adapter = make_adapter(profile, key, params["model"], app=job)
    options = AnalysisOptions(**decamelize(params.get("options", {})))
    pipeline = DiscoveryPipeline(
        runs=job.ctx.runs,
        candidates=job.ctx.candidates,
        transcripts=job.ctx.transcripts,
        sources=job.ctx.sources,
    )
    hooks = AnalysisHooks(
        progress=lambda stage, fraction, message: job.progress(stage, fraction, message),
        state=job.state,
        wait=job.wait,
        checkpoint=job.save_checkpoint,
        cancel=job.cancel_event,
        request_log=_request_logger(job.ctx),
    )
    result = await pipeline.run(
        source=source,
        transcript=transcript,
        adapter=adapter,
        provider_profile_id=profile["id"],
        model=params["model"],
        options=options,
        hooks=hooks,
        checkpoint=job.checkpoint,
    )
    return {**result, "provider": profile["name"]}


def app_source(job, source_id: str) -> dict[str, Any]:
    source = job.ctx.sources.get(source_id)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    return source


def _sidecar_captions(path: Path) -> list[Path]:
    out = []
    for suffix in CAPTION_SUFFIXES:
        candidate = path.with_suffix(suffix)
        if candidate.exists():
            out.append(candidate)
        for extra in path.parent.glob(f"{path.stem}.*{suffix}"):
            if extra not in out:
                out.append(extra)
    return out


async def transcription_job(job, params: dict[str, Any]) -> dict[str, Any]:
    source = app_source(job, params["sourceId"])
    work = job.ctx.paths.job_tmp(job.job_id)
    engine = params["engine"]
    model = params.get("model")
    language = params.get("language")
    prefer_captions = bool(params.get("preferCaptions", True))
    def job_progress(fraction: float, message: str) -> None:
        job.progress("transcribing", fraction, message)

    job.progress("preparing", 0.02, "Preparing the transcript…")
    source_for_transcription = dict(source)
    media_path: Path | None = None
    caption_files: list[Path] = []

    if source["kind"] == "url" and prefer_captions:
        job.progress("captions", 0.04, "Checking for captions that came with the video…")
        languages = None
        if language:
            # Put the wildcard first. yt-dlp stops at the first failed language
            # request; asking for "en,en.*" can hit the translated "en" (429)
            # before the original "en-orig" caption and throw away a usable file.
            base_language = language.replace("_", "-").split("-", 1)[0]
            languages = [f"{base_language}.*", base_language]
        try:
            caption_files = await job.ctx.ytdlp.download_subtitles(
                source["url"], work / "captions", languages=languages, allow_auto=True, cancel=job.cancel_event
            )
        except EngineError as exc:
            job.log("warn", f"Caption download failed: {exc.message}")
            caption_files = []
        if caption_files:
            try:
                transcript = await job.ctx.transcription.from_captions(
                    source, caption_files, progress=job_progress, cancel=job.cancel_event
                )
                if transcript:
                    return _transcript_result(job, source, transcript, "subtitle")
            except EngineError as exc:
                job.log("warn", f"Captions were unusable: {exc.message}")
    elif source["kind"] == "file":
        local = Path(source.get("localPath") or "")
        caption_files = _sidecar_captions(local)
        if caption_files and prefer_captions:
            try:
                transcript = await job.ctx.transcription.from_captions(
                    source, caption_files, progress=job_progress, cancel=job.cancel_event
                )
                if transcript:
                    return _transcript_result(job, source, transcript, "subtitle")
            except EngineError as exc:
                job.log("warn", f"Sidecar captions were unusable: {exc.message}")

    prepared = job.ctx.transcription.prepared_audio(source, engine)
    if prepared:
        media_path = prepared
        job.progress("audio", 0.2, "Reusing audio prepared earlier…")
    elif source["kind"] == "url":
        job.progress("audio", 0.1, "Downloading only the audio track…")
        if not source.get("url"):
            raise EngineError("SOURCE_MISSING", "This source has no URL to download from.")
        try:
            media_path = await job.ctx.ytdlp.download_audio(source["url"], work / "audio", cancel=job.cancel_event)
        except EngineError as exc:
            exc.details.setdefault("hint", "DOWNLOAD_OR_LOCAL_FILE")
            raise
        job.progress("audio", 0.2, "Audio downloaded.")
    else:
        media_path = Path(source.get("localPath") or "")
        if not media_path.exists():
            raise EngineError("SOURCE_MISSING", "The source file has moved. Re-import it.")

    provider = None
    api_key = None
    if engine == "cloud_openai":
        profile = job.ctx.providers.get(params.get("providerProfileId") or "")
        if not profile:
            from .methods.providers import default_profile

            profile = default_profile(job)
        api_key = resolve_key(profile, job.secrets)
        provider = profile

    def transcribe_progress(fraction: float, message: str) -> None:
        job.progress("transcribing", fraction, message)

    transcript = await job.ctx.transcription.transcribe(
        source_for_transcription,
        engine=engine,
        language=language,
        model_name=model,
        progress=transcribe_progress,
        cancel=job.cancel_event,
        job_tmp=work,
        provider=provider,
        api_key=api_key,
        media_path=media_path,
    )
    if transcript.get("language"):
        job.ctx.sources.update(source["id"], language=transcript["language"])
    return _transcript_result(job, source, transcript, transcript.get("origin", engine))


def _transcript_result(job, source: dict[str, Any], transcript: dict[str, Any], origin: str) -> dict[str, Any]:
    return {
        "transcriptId": transcript["id"],
        "sourceId": source["id"],
        "origin": transcript.get("origin") or origin,
        "engine": transcript.get("engine"),
        "model": transcript.get("model"),
        "language": transcript.get("language"),
        "wordTiming": transcript.get("wordTiming"),
        "segmentCount": len(transcript.get("segments") or []),
        "durationS": (transcript.get("segments") or [{}])[-1].get("endS") if transcript.get("segments") else None,
    }


async def render_job(job, params: dict[str, Any]) -> dict[str, Any]:
    selection_ids: list[str] = list(params["selectionIds"])
    total = len(selection_ids)
    completed = list(job.checkpoint.get("completed") or [])
    options = RenderOptions(
        output_dir=Path(params["outputDir"]),
        quality=params.get("quality", "standard"),
        prefer_hardware=bool(params.get("preferHardware", True)),
        filename_template=params.get("filenameTemplate") or "{title}-{index}-{start}",
    )
    items: list[dict[str, Any]] = []
    succeeded = 0
    encoder = None
    for position, selection_id in enumerate(selection_ids):
        if selection_id in completed:
            succeeded += 1
            continue
        if job.cancel_event.is_set():
            break

        def progress(sid: str, index: int, count: int, fraction: float, message: str, position=position) -> None:
            overall = (position + max(0.0, min(1.0, fraction))) / max(1, total)
            job.progress("render", overall, message)

        hooks = RenderHooks(
            progress=progress,
            state=job.state,
            log=job.log,
            item_done=lambda item: None,
            cancel=job.cancel_event,
        )
        result = await job.ctx.render.render_batch(
            project_id=params["projectId"],
            selection_ids=[selection_id],
            options=options,
            hooks=hooks,
            job_tmp=job.ctx.paths.job_tmp(job.job_id),
        )
        encoder = result.get("encoder") or encoder
        items.extend(result.get("items") or [])
        if result.get("succeeded"):
            succeeded += 1
            completed.append(selection_id)
            job.save_checkpoint({"completed": completed})
        else:
            job.log("error", f"Clip {position + 1} failed; continuing with the rest of the queue.")
    if job.cancel_event.is_set():
        from ..common.errors import CancelledError

        raise CancelledError()
    return {
        "selectionCount": total,
        "succeeded": succeeded,
        "failed": total - succeeded,
        "items": items,
        "encoder": encoder,
    }


async def model_download_job(job, params: dict[str, Any]) -> dict[str, Any]:
    record = await job.ctx.models.download(
        params["kind"], params["name"], progress=lambda f, m: job.progress("download", f, m), cancel=job.cancel_event
    )
    return {"model": record}
