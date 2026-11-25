from __future__ import annotations

from enum import Enum
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(str, Enum):
    funny = "funny"
    educational = "educational"
    storytelling = "storytelling"
    surprising = "surprising"
    emotional = "emotional"
    controversial = "controversial"
    insight = "insight"
    strong_hook = "strong_hook"
    best_overall = "best_overall"


CATEGORY_ORDER: list[str] = [c.value for c in Category]


class Rating(BaseModel):
    """One ordinal rating with the evidence the model used for it."""

    model_config = ConfigDict(extra="ignore")

    score: int = Field(ge=1, le=5)
    evidence: str = Field(default="", max_length=600)


class Ratings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hook_strength: Rating
    context_completeness: Rating
    ending_quality: Rating
    standalone_clarity: Rating


def _normalize_segment_id(value: object) -> object:
    """Accept a segment ID with a copied transcript line suffix.

    Small local models sometimes copy the whole `[s0001|00:00:06]` prompt
    label into `start_seg`. The ID is still unambiguous; keep the contract
    strict by extracting only the `s0001` prefix. Raw timestamps are not IDs
    and are still rejected by the field pattern.
    """
    if isinstance(value, str):
        match = re.match(r"^\s*(s\d{4,6})(?:\b|$)", value)
        if match:
            return match.group(1)
    return value


class CandidateProposal(BaseModel):
    """What the model is allowed to return: segment-id ranges, never timestamps."""

    model_config = ConfigDict(extra="ignore")

    category: Category
    start_seg: str = Field(pattern=r"^s\d{4,6}$")
    end_seg: str = Field(pattern=r"^s\d{4,6}$")
    title: str = Field(min_length=3, max_length=140)
    excerpt: str = Field(default="", max_length=400)
    rationale: str = Field(min_length=10, max_length=1200)
    ratings: Ratings
    weaknesses: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("start_seg", "end_seg", mode="before")
    @classmethod
    def normalize_segment_ids(cls, value: object) -> object:
        return _normalize_segment_id(value)

    @field_validator("weaknesses")
    @classmethod
    def trim_weaknesses(cls, value: list[str]) -> list[str]:
        return [v.strip()[:300] for v in value if v.strip()][:8]


class WindowAnalysis(BaseModel):
    model_config = ConfigDict(extra="ignore")

    candidates: list[CandidateProposal] = Field(default_factory=list, max_length=12)


class RankedItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start_seg: str = Field(pattern=r"^s\d{4,6}$")
    end_seg: str = Field(pattern=r"^s\d{4,6}$")
    rank: int = Field(ge=1)
    best_overall: bool = False

    @field_validator("start_seg", "end_seg", mode="before")
    @classmethod
    def normalize_segment_ids(cls, value: object) -> object:
        return _normalize_segment_id(value)


class RankedCandidates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ranking: list[RankedItem] = Field(default_factory=list, max_length=30)


class ClipMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=3, max_length=120)
    description: str = Field(default="", max_length=1200)
    hashtags: list[str] = Field(default_factory=list, max_length=12)
    hook_suggestions: list[str] = Field(default_factory=list, max_length=5)
    thumbnail_text: list[str] = Field(default_factory=list, max_length=5)
    thumbnail_time_s: float | None = None


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


class ProviderCapabilities(BaseModel):
    """Capability probes are advisory; every structured call still validates output."""

    model_config = ConfigDict(extra="ignore", alias_generator=_camel, populate_by_name=True)

    supports_json_schema: bool = False
    supports_json_schema_strict: bool = False
    supports_json_object: bool = True
    supports_vision: bool = False
    supports_audio_transcription: bool = False
    context_tokens: int = 8192
    max_output_tokens: int = 2048
    probed_at: str | None = None
    probe_note: str | None = None


class ProviderProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    adapter: Literal["groq", "openai_compatible", "custom"]
    base_url: str
    default_model: str | None = None
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities)
    enabled: bool = True


class ProviderModel(BaseModel):
    id: str
    owned_by: str | None = None
    context_window: int | None = None
    active: bool = True
