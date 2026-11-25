from __future__ import annotations

from typing import Any

from ..common.brand import PROTOCOL_VERSION
from ..common.errors import EngineError
from pydantic import BaseModel, ConfigDict, Field


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False

    @classmethod
    def from_error(cls, err: EngineError) -> "ErrorPayload":
        return cls(**err.to_dict())


class Request(BaseModel):
    model_config = ConfigDict(extra="allow")

    v: int = PROTOCOL_VERSION
    id: str
    kind: str = "request"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)


class Response(BaseModel):
    v: int = PROTOCOL_VERSION
    id: str
    kind: str = "response"
    result: dict[str, Any] | None = None
    error: ErrorPayload | None = None


class Event(BaseModel):
    v: int = PROTOCOL_VERSION
    id: str = ""
    kind: str = "event"
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class EngineInfo(BaseModel):
    engineVersion: str
    protocolVersion: int
    productName: str
    capabilities: list[str]
    dataDir: str
    platform: str
    python: str
