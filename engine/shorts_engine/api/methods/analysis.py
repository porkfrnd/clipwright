from __future__ import annotations

import asyncio
from typing import Any

from ...common.errors import CancelledError, EngineError
from ..params import (
    AnalysisEstimateParams,
    AnalysisListParams,
    AnalysisStartParams,
    CandidateIdParams,
    CandidateRenameParams,
    CandidateStatusParams,
    CandidateUpdateBoundsParams,
    CandidatesListParams,
    EditSetParams,
    MetadataGenerateParams,
    SelectionIdParams,
    SelectionListParams,
    SelectionSetParams,
    TranscriptionStartParams,
    TranscriptGetParams,
)
from ..registry import Registry
from .providers import get_profile, make_adapter, resolve_key


def register(registry: Registry) -> None:
    registry.add("transcription.start", TranscriptionStartParams, transcription_start)
    registry.add("transcript.get", TranscriptGetParams, transcript_get)
    registry.add("transcript.list", AnalysisListParams, transcript_list)
    registry.add("analysis.start", AnalysisStartParams, analysis_start)
    registry.add("analysis.estimate", AnalysisEstimateParams, analysis_estimate)
    registry.add("analysis.list", AnalysisListParams, analysis_list)
    registry.add("candidates.list", CandidatesListParams, candidates_list)
    registry.add("candidates.update_bounds", CandidateUpdateBoundsParams, candidates_update_bounds)
    registry.add("candidates.revisions", CandidateIdParams, candidates_revisions)
    registry.add("candidates.undo", CandidateIdParams, candidates_undo)
    registry.add("candidates.rename", CandidateRenameParams, candidates_rename)
    registry.add("candidates.set_status", CandidateStatusParams, candidates_set_status)
    registry.add("selection.set", SelectionSetParams, selection_set)
    registry.add("selection.list", SelectionListParams, selection_list)
    registry.add("edit.get", SelectionIdParams, edit_get)
    registry.add("edit.set", EditSetParams, edit_set)
    registry.add("metadata.generate", MetadataGenerateParams, metadata_generate)


async def transcription_start(app, params: TranscriptionStartParams, secrets) -> dict[str, Any]:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    settings = app.ctx.settings.get("transcription", {})
    model = params.model or (
        settings.get("localModel") if params.engine == "local_whisper" else settings.get("cloudModel")
    )
    if params.engine == "local_whisper" and not app.ctx.models.path_for("whisper", model or "small"):
        raise EngineError(
            "MODEL_NOT_INSTALLED",
            "That local Whisper model is not installed. Download it in Model Manager first.",
            details={"model": model},
        )
    provider_id = params.providerProfileId or settings.get("providerProfileId")
    if params.engine == "cloud_openai":
        profile = get_profile(app, provider_id)
        resolve_key(profile, secrets)  # fail early, before a job is queued
        provider_id = profile["id"]
    job = await app.ctx.job_manager.start(
        "transcription",
        {
            "sourceId": source["id"],
            "engine": params.engine,
            "model": model,
            "language": params.language or settings.get("language"),
            "providerProfileId": provider_id,
            "preferCaptions": params.preferCaptions,
        },
        source["projectId"],
        secrets,
    )
    return job


def _transcript_for(
    app, transcript_id: str | None, source_id: str | None, *, include_words: bool = True
) -> dict[str, Any]:
    if transcript_id:
        transcript = app.ctx.transcripts.get(transcript_id, include_words=include_words)
    elif source_id:
        transcript = app.ctx.transcripts.latest_for_source(source_id, include_words=include_words)
    else:
        transcript = None
    if not transcript:
        raise EngineError("TRANSCRIPT_NOT_FOUND", "No transcript is available yet.")
    return transcript


async def transcript_get(app, params: TranscriptGetParams, secrets) -> dict[str, Any]:
    transcript = _transcript_for(
        app, params.transcriptId, params.sourceId, include_words=params.includeWords
    )
    return {"transcript": transcript}


async def transcript_list(app, params: AnalysisListParams, secrets) -> dict[str, Any]:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    return {"transcripts": source.get("transcripts", [])}


async def analysis_start(app, params: AnalysisStartParams, secrets) -> dict[str, Any]:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    transcript = _transcript_for(app, params.transcriptId, params.sourceId)
    profile = get_profile(app, params.providerProfileId)
    resolve_key(profile, secrets)
    model = params.model or profile.get("defaultModel")
    if not model:
        raise EngineError(
            "MODEL_REQUIRED",
            "Choose a model for this provider. Use Settings → AI providers to load the model list.",
        )
    options = {**app.ctx.settings.get("analysis", {}), **(params.options or {})}
    job = await app.ctx.job_manager.start(
        "analysis",
        {
            "sourceId": source["id"],
            "transcriptId": transcript["id"],
            "providerProfileId": profile["id"],
            "model": model,
            "options": {
                "maxCandidatesPerWindow": int(options.get("maxCandidatesPerWindow", 5)),
                "windowSeconds": float(options.get("windowSeconds", 360)),
                "overlap": float(options.get("overlap", 0.22)),
                "minDuration": float(options.get("minDuration", 15)),
                "maxDuration": float(options.get("maxDuration", 90)),
                "rankWithAi": bool(options.get("rankWithAi", True)),
                "batchSize": max(1, min(4, int(options.get("batchSize", 2)))),
            },
        },
        source["projectId"],
        secrets,
    )
    return job


async def analysis_estimate(app, params: AnalysisEstimateParams, secrets) -> dict[str, Any]:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    transcript = app.ctx.transcripts.latest_for_source(params.sourceId)
    if not transcript:
        raise EngineError("TRANSCRIPT_NOT_FOUND", "Transcribe the source first to estimate analysis usage.")
    profile = get_profile(app, params.providerProfileId)
    model = params.model or profile.get("defaultModel") or "unknown"
    options = app.ctx.settings.get("analysis", {})
    segments = transcript["segments"]
    from ...discovery.chunker import batch_windows, build_windows

    windows = build_windows(
        segments,
        target_s=float(options.get("windowSeconds", 360)),
        overlap=float(options.get("overlap", 0.22)),
    )
    from ...common.util import estimate_tokens

    transcript_tokens = sum(estimate_tokens(s["text"]) for s in segments)
    batches = batch_windows(windows, size=int(options.get("batchSize", 2)))
    per_batch = transcript_tokens / max(1, len(batches))
    overhead = 700
    map_tokens = int(len(batches) * (per_batch + overhead) * 1.2)
    rank_tokens = int(min(15000, len(batches) * 500 + 1200))
    return {
        "model": model,
        "windows": len(windows),
        "batches": len(batches),
        "requests": len(batches) + (1 if len(batches) > 1 else 0),
        "estimatedTokens": map_tokens + rank_tokens,
        "transcriptTokens": transcript_tokens,
        "durationMinutes": round(float(source.get("durationS") or 0) / 60, 1),
        "note": "Estimate only. Actual usage and rate limits come from the provider response headers.",
    }


async def analysis_list(app, params: AnalysisListParams, secrets) -> dict[str, Any]:
    return {"runs": app.ctx.runs.list(params.sourceId)}


async def candidates_list(app, params: CandidatesListParams, secrets) -> dict[str, Any]:
    return {"candidates": app.ctx.candidates.list(params.sourceId, params.runId)}


async def candidates_update_bounds(app, params: CandidateUpdateBoundsParams, secrets) -> dict[str, Any]:
    if params.endS <= params.startS:
        raise EngineError("INVALID_RANGE", "The clip end must be after its start.")
    if params.endS - params.startS < 3:
        raise EngineError("CLIP_TOO_SHORT", "Clips must be at least 3 seconds long.")
    if params.endS - params.startS > 300:
        raise EngineError("CLIP_TOO_LONG", "Clips in the Studio are limited to 5 minutes.")
    candidate = app.ctx.candidates.get(params.candidateId)
    if not candidate:
        raise EngineError("CANDIDATE_NOT_FOUND", "That clip moment no longer exists.")
    updated = app.ctx.candidates.update_bounds(params.candidateId, params.startS, params.endS, "user")
    return {"candidate": updated}


async def candidates_revisions(app, params: CandidateIdParams, secrets) -> dict[str, Any]:
    if not app.ctx.candidates.get(params.candidateId):
        raise EngineError("CANDIDATE_NOT_FOUND", "That clip moment no longer exists.")
    return {"revisions": app.ctx.candidates.revisions(params.candidateId)}


async def candidates_undo(app, params: CandidateIdParams, secrets) -> dict[str, Any]:
    updated = app.ctx.candidates.undo(params.candidateId)
    if not updated:
        raise EngineError("NOTHING_TO_UNDO", "There is no earlier boundary edit to restore.")
    return {"candidate": updated}


async def candidates_rename(app, params: CandidateRenameParams, secrets) -> dict[str, Any]:
    app.ctx.candidates.rename(params.candidateId, params.title)
    return {"candidate": app.ctx.candidates.get(params.candidateId)}


async def candidates_set_status(app, params: CandidateStatusParams, secrets) -> dict[str, Any]:
    app.ctx.candidates.set_status(params.candidateId, params.status)
    return {"candidate": app.ctx.candidates.get(params.candidateId)}


async def selection_set(app, params: SelectionSetParams, secrets) -> dict[str, Any]:
    project = app.ctx.projects.get(params.projectId)
    if not project:
        raise EngineError("PROJECT_NOT_FOUND", "That project no longer exists.")
    for candidate_id in params.candidateIds:
        if not app.ctx.candidates.get(candidate_id):
            raise EngineError("CANDIDATE_NOT_FOUND", "One of the selected clips no longer exists.")
    selections = app.ctx.selections.set(params.projectId, params.candidateIds, params.presetId)
    if params.presetId:
        preset = next((p for p in app.ctx.presets.list() if p["id"] == params.presetId), None)
        if preset:
            for selection in selections:
                app.ctx.edits.set(selection["id"], preset["settings"])
    detailed = []
    for selection in selections:
        candidate = app.ctx.candidates.get(selection["candidateId"])
        if candidate:
            detailed.append({**selection, "candidate": candidate, "edit": app.ctx.edits.get(selection["id"])})
    app.ctx.projects.touch(params.projectId)
    return {"selections": detailed}


async def selection_list(app, params: SelectionListParams, secrets) -> dict[str, Any]:
    selections = app.ctx.selections.list(params.projectId)
    detailed = []
    for selection in selections:
        candidate = app.ctx.candidates.get(selection["candidateId"])
        if candidate:
            detailed.append({**selection, "candidate": candidate, "edit": app.ctx.edits.get(selection["id"])})
    return {"selections": detailed}


async def edit_get(app, params: SelectionIdParams, secrets) -> dict[str, Any]:
    selection = app.ctx.selections.get(params.selectionId)
    if not selection:
        raise EngineError("SELECTION_NOT_FOUND", "That clip is not selected.")
    return {"edit": app.ctx.edits.get(params.selectionId), "selection": selection}


async def edit_set(app, params: EditSetParams, secrets) -> dict[str, Any]:
    selection = app.ctx.selections.get(params.selectionId)
    if not selection:
        raise EngineError("SELECTION_NOT_FOUND", "That clip is not selected.")
    if not isinstance(params.settings, dict):
        raise EngineError("INVALID_PARAMS", "Edit settings must be an object.")
    updated = app.ctx.edits.set(params.selectionId, params.settings)
    app.ctx.projects.touch(selection["projectId"])
    return {"edit": updated}


async def metadata_generate(app, params: MetadataGenerateParams, secrets) -> dict[str, Any]:
    candidate = app.ctx.candidates.get(params.candidateId)
    if not candidate:
        raise EngineError("CANDIDATE_NOT_FOUND", "That clip moment no longer exists.")
    source = app.ctx.sources.get(candidate["sourceId"])
    transcript = app.ctx.transcripts.latest_for_source(candidate["sourceId"])
    if not source or not transcript:
        raise EngineError("TRANSCRIPT_NOT_FOUND", "The transcript for this clip is missing.")
    run = app.ctx.runs.get(candidate["analysisRunId"])
    profile = get_profile(app, params.providerProfileId or (run or {}).get("providerProfileId"))
    key = resolve_key(profile, secrets)
    model = params.model or (run or {}).get("model") or profile.get("defaultModel")
    if not model:
        raise EngineError("MODEL_REQUIRED", "Choose a model for this provider first.")
    excerpt = " ".join(
        s["text"]
        for s in transcript["segments"]
        if float(s["endS"]) > candidate["startS"] and float(s["startS"]) < candidate["endS"]
    )[:6000]
    from ...ai.adapter import AdapterHooks
    from ...ai.contract import MomentAI

    adapter = make_adapter(profile, key, model, app=app)
    hooks = AdapterHooks(
        on_request=lambda provider, mod, op, tokens, cats, outcome: app.ctx.request_log.add(
            provider, mod, op, tokens, cats, outcome
        )
    )
    ai = MomentAI(adapter)
    result, chat = await ai.generate_metadata(
        title=candidate["title"],
        duration=candidate["durationS"],
        source_title=source.get("title") or "Untitled",
        transcript=excerpt,
        hooks=hooks,
    )
    return {
        "metadata": result.model_dump(mode="json"),
        "aiGenerated": True,
        "provider": profile["name"],
        "model": model,
        "usage": {"totalTokens": chat.total_tokens},
        "disclosure": "AI-generated. Edit before publishing; it is never spoken or burned into the video unless you add it.",
    }
