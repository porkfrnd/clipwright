from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Empty(Strict):
    pass


class HelloParams(Strict):
    protocolVersion: int = 1
    appVersion: str | None = None


class ProjectCreateParams(Strict):
    name: str = Field(min_length=1, max_length=120)


class ProjectIdParams(Strict):
    projectId: str = Field(min_length=1)


class ProjectRenameParams(Strict):
    projectId: str
    name: str = Field(min_length=1, max_length=120)


class ImportFileParams(Strict):
    projectId: str
    path: str = Field(min_length=1)
    authorizationAckAt: str | None = None


class ImportUrlParams(Strict):
    projectId: str
    url: str = Field(min_length=1, max_length=2048)
    authorizationAckAt: str = Field(min_length=1)


class SourceIdParams(Strict):
    sourceId: str


class FetchPreviewParams(Strict):
    sourceId: str
    startS: float = Field(ge=0, le=86400)
    endS: float = Field(gt=0, le=86400)


class TranscriptionStartParams(Strict):
    sourceId: str
    engine: Literal["local_whisper", "cloud_openai"]
    model: str | None = None
    language: str | None = Field(default=None, max_length=20)
    providerProfileId: str | None = None
    preferCaptions: bool = True


class TranscriptGetParams(Strict):
    transcriptId: str | None = None
    sourceId: str | None = None
    includeWords: bool = True


class AnalysisStartParams(Strict):
    sourceId: str
    providerProfileId: str | None = None
    model: str | None = None
    transcriptId: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class AnalysisListParams(Strict):
    sourceId: str


class AnalysisEstimateParams(Strict):
    sourceId: str
    providerProfileId: str | None = None
    model: str | None = None


class CandidatesListParams(Strict):
    sourceId: str
    runId: str | None = None


class CandidateUpdateBoundsParams(Strict):
    candidateId: str
    startS: float = Field(ge=0, le=86400)
    endS: float = Field(gt=0, le=86400)


class CandidateIdParams(Strict):
    candidateId: str


class CandidateRenameParams(Strict):
    candidateId: str
    title: str = Field(min_length=1, max_length=140)


class CandidateStatusParams(Strict):
    candidateId: str
    status: Literal["proposed", "edited", "rejected"]


class SelectionSetParams(Strict):
    projectId: str
    candidateIds: list[str] = Field(default_factory=list, max_length=200)
    presetId: str | None = None


class SelectionIdParams(Strict):
    selectionId: str


class SelectionListParams(Strict):
    projectId: str


class EditSetParams(Strict):
    selectionId: str
    settings: dict[str, Any]


class PresetSaveParams(Strict):
    name: str = Field(min_length=1, max_length=80)
    settings: dict[str, Any]
    presetId: str | None = None


class PresetDeleteParams(Strict):
    presetId: str


class ProviderSaveParams(Strict):
    profile: dict[str, Any]


class ProviderIdParams(Strict):
    profileId: str


class ProviderTestParams(Strict):
    profileId: str | None = None
    adapter: Literal["groq", "openai_compatible", "custom", "local"] | None = None
    baseUrl: str | None = None
    model: str | None = None
    probe: bool = True


class ProviderModelsParams(Strict):
    profileId: str


class SettingsSetParams(Strict):
    key: Literal["app", "transcription", "analysis", "render", "privacy", "wizard", "hardware", "downloads", "providers"]
    value: dict[str, Any]


class SettingsGetParams(Strict):
    key: str | None = None


class ModelIdParams(Strict):
    modelId: str


class ModelDownloadParams(Strict):
    kind: Literal["whisper", "face", "llm"]
    name: str


class RenderStartParams(Strict):
    projectId: str
    selectionIds: list[str] = Field(min_length=1, max_length=100)
    outputDir: str | None = None
    quality: Literal["standard", "high"] = "standard"
    preferHardware: bool = True
    filenameTemplate: str | None = None


class RenderQueueParams(Strict):
    projectId: str


class JobIdParams(Strict):
    jobId: str


class JobsListParams(Strict):
    projectId: str | None = None
    activeOnly: bool = False


class MetadataGenerateParams(Strict):
    candidateId: str
    providerProfileId: str | None = None
    model: str | None = None


class BinariesUpdateParams(Strict):
    channel: Literal["stable", "nightly"] = "stable"


class MediaResolveParams(Strict):
    assetId: str


class SourceAuthorizationParams(Strict):
    sourceId: str
    authorizationAckAt: str = Field(min_length=1)
