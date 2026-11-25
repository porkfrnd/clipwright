from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..common.paths import AppPaths
from ..common.proc import ProcessRunner
from ..common.resources import repo_root
from ..hardware.detect import HardwareDetector
from ..ingest.audio import AudioTools
from ..ingest.binaries import BinaryPaths, find_binaries
from ..ingest.probe import Prober
from ..ingest.ytdlp import YtDlp
from ..models.manager import ModelManager
from ..render.encoder import EncoderProbe
from ..render.presets import BUILTIN_PRESETS
from ..render.service import RenderService
from ..storage.db import Database
from ..storage.repos import (
    AnalysisRunRepo,
    AssetRepo,
    CandidateRepo,
    EditRepo,
    ExportJobRepo,
    JobRepo,
    ModelRepo,
    PresetRepo,
    ProjectRepo,
    ProviderRepo,
    RequestLogRepo,
    SelectionRepo,
    SettingsRepo,
    SourceRepo,
    DEFAULT_EDIT,
    TranscriptRepo,
)
from ..transcription.service import TranscriptionService

DEFAULT_PROVIDER_ID = "groq-default"

DEFAULT_SETTINGS: dict[str, Any] = {
    "app": {
        "theme": "velvet",
        "appearance": "dark",
        "density": "comfortable",
        "reduceMotion": False,
        "effects": True,
    },
    "transcription": {
        "engine": "cloud_openai",
        "localModel": "small",
        "cloudModel": "whisper-large-v3-turbo",
        "providerProfileId": DEFAULT_PROVIDER_ID,
        "preferCaptions": True,
        "language": None,
    },
    "analysis": {
        "maxCandidatesPerWindow": 5,
        "windowSeconds": 360,
        "overlap": 0.22,
        "minDuration": 15,
        "maxDuration": 90,
        "rankWithAi": True,
        "visionEnabled": False,
    },
    "render": {
        "quality": "standard",
        "preferHardware": True,
        "filenameTemplate": "{title}-{index}-{start}",
        "fps": 30,
    },
    "privacy": {
        "authorizationAcknowledgedAt": None,
        "providerDisclosureAt": None,
        "requestLogEnabled": True,
    },
    "wizard": {"completed": False},
    "hardware": {"profile": "auto"},
    "downloads": {"channel": "stable", "autoUpdateYtdlp": False, "cookiesFile": None},
}


@dataclass
class AppContext:
    paths: AppPaths
    db: Database
    bins: BinaryPaths
    runner: ProcessRunner
    prober: Prober
    audio: AudioTools
    ytdlp: YtDlp
    models: ModelManager
    hardware: HardwareDetector
    encoder_probe: EncoderProbe
    transcription: TranscriptionService
    render: RenderService
    preview_locks: dict[str, asyncio.Lock]

    projects: ProjectRepo
    sources: SourceRepo
    assets: AssetRepo
    transcripts: TranscriptRepo
    candidates: CandidateRepo
    runs: AnalysisRunRepo
    selections: SelectionRepo
    edits: EditRepo
    presets: PresetRepo
    providers: ProviderRepo
    request_log: RequestLogRepo
    jobs: JobRepo
    exports: ExportJobRepo
    model_repo: ModelRepo
    settings: SettingsRepo


def build_context(paths: AppPaths) -> AppContext:
    db = Database(paths.db_path)
    runner = ProcessRunner()
    bins = find_binaries(paths, repo_root())
    prober = Prober(bins, runner)
    audio = AudioTools(bins, runner)
    ytdlp = YtDlp(bins, runner)
    model_repo = ModelRepo(db)
    models = ModelManager(paths.models, model_repo)
    encoder_probe = EncoderProbe(bins, runner)
    hardware = HardwareDetector(paths, bins, runner)

    projects = ProjectRepo(db)
    sources = SourceRepo(db)
    assets = AssetRepo(db)
    transcripts = TranscriptRepo(db)
    candidates = CandidateRepo(db)
    runs = AnalysisRunRepo(db)
    selections = SelectionRepo(db)
    edits = EditRepo(db)
    presets = PresetRepo(db)
    providers = ProviderRepo(db)
    request_log = RequestLogRepo(db)
    jobs = JobRepo(db)
    exports = ExportJobRepo(db)
    settings = SettingsRepo(db)
    ytdlp.cookies_file = settings.get("downloads", {}).get("cookiesFile")

    transcription = TranscriptionService(paths, audio, models, transcripts, sources, assets)
    render = RenderService(
        paths=paths,
        bins=bins,
        runner=runner,
        prober=prober,
        audio=audio,
        ytdlp=ytdlp,
        encoder_probe=encoder_probe,
        candidates=candidates,
        selections=selections,
        edits=edits,
        sources=sources,
        transcripts=transcripts,
        runs=runs,
        assets=assets,
        exports=exports,
    )
    ctx = AppContext(
        paths=paths,
        db=db,
        bins=bins,
        runner=runner,
        prober=prober,
        audio=audio,
        ytdlp=ytdlp,
        models=models,
        hardware=hardware,
        encoder_probe=encoder_probe,
        transcription=transcription,
        render=render,
        preview_locks={},
        projects=projects,
        sources=sources,
        assets=assets,
        transcripts=transcripts,
        candidates=candidates,
        runs=runs,
        selections=selections,
        edits=edits,
        presets=presets,
        providers=providers,
        request_log=request_log,
        jobs=jobs,
        exports=exports,
        model_repo=model_repo,
        settings=settings,
    )
    seed(ctx)
    return ctx


def seed(ctx: AppContext) -> None:
    existing = ctx.settings.get("app")
    if not existing:
        for key, value in DEFAULT_SETTINGS.items():
            ctx.settings.set(key, value)
    render_settings = ctx.settings.get("render", {})
    if not render_settings.get("outputDir"):
        render_settings["outputDir"] = str(ctx.paths.outputs)
        ctx.settings.set("render", render_settings)
    if not ctx.providers.list():
        ctx.providers.save(
            {
                "id": DEFAULT_PROVIDER_ID,
                "name": "Groq",
                "adapter": "groq",
                "base_url": "https://api.groq.com/openai/v1",
                "default_model": "openai/gpt-oss-20b",
                "capabilities": {
                    "supports_json_schema": True,
                    "supports_json_schema_strict": True,
                    "supports_json_object": True,
                    "context_tokens": 131072,
                    "max_output_tokens": 4096,
                    "audio_transcription": True,
                },
                "enabled": True,
            }
        )
    ctx.presets.seed(BUILTIN_PRESETS)
    if not any(p["name"] == "Custom" for p in ctx.presets.list()):
        import json

        ctx.presets.save("Custom", json.loads(json.dumps(DEFAULT_EDIT)))
    ctx.jobs.recover_interrupted()
    ctx.paths.sweep_tmp()
