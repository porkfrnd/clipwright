"""Local GGUF provider tests that do not need a real 600 MB model."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from shorts_engine.ai.adapter import LocalLlamaAdapter
from shorts_engine.api.methods.providers import make_adapter, validate_local_base_url
from shorts_engine.models.catalog import LLM_MODELS, llm_catalog


class Point(BaseModel):
    ok: bool


class FakeLlama:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.init_kwargs = kwargs

    def create_chat_completion(self, **kwargs):
        FakeLlama.calls.append(kwargs)
        return {
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
        }


def test_llm_catalog_has_pinned_qwen():
    assert llm_catalog()[0]["kind"] == "llm"
    assert llm_catalog()[0]["name"] == "qwen3-0.6b"
    assert LLM_MODELS[0]["filename"].endswith(".gguf")
    assert len(LLM_MODELS[0]["sha256"]) == 64


def test_validate_local_url_rejects_http_endpoint():
    assert validate_local_base_url("local://qwen3-0.6b") == "local://qwen3-0.6b"
    with pytest.raises(Exception):
        validate_local_base_url("https://api.example.com/v1")


async def test_local_adapter_prompt_and_schema(tmp_path: Path):
    model_file = tmp_path / "fake.gguf"
    model_file.write_bytes(b"fake")
    adapter = LocalLlamaAdapter(
        model="qwen3-0.6b",
        model_path=model_file,
        llama_factory=FakeLlama,
    )
    result = await adapter.chat_structured(
        schema_model=Point,
        system="You are a JSON API.",
        user='Return {"ok": true}.',
        operation="test",
        max_tokens=32,
        temperature=0,
    )
    assert result.parsed.ok is True
    assert result.mode == "prompt"
    assert result.total_tokens == 16
    assert FakeLlama.calls
    messages = FakeLlama.calls[-1]["messages"]
    assert "/no_think" in messages[-1]["content"]
    assert "JSON Schema" in messages[0]["content"]
    assert adapter.model == "qwen3-0.6b"


async def test_local_adapter_reports_missing_model(tmp_path: Path):
    adapter = LocalLlamaAdapter(
        model="qwen3-0.6b",
        model_path=tmp_path / "missing.gguf",
        llama_factory=FakeLlama,
    )
    with pytest.raises(Exception) as exc:
        await adapter.chat_structured(
            schema_model=Point,
            system="Return JSON.",
            user="Return true.",
            operation="test",
        )
    assert getattr(exc.value, "code", "") == "LOCAL_MODEL_NOT_INSTALLED"


async def test_make_adapter_resolves_installed_model(tmp_path: Path):
    model_file = tmp_path / "Qwen3-0.6B-Q8_0.gguf"
    model_file.write_bytes(b"fake")

    class Models:
        def llm_path(self, name: str):
            return model_file if name == "qwen3-0.6b" else None

    class Ctx:
        models = Models()

    class App:
        ctx = Ctx()

    adapter = make_adapter(
        {"adapter": "local", "baseUrl": "local://qwen3-0.6b", "capabilities": {}},
        "local",
        "qwen3-0.6b",
        app=App(),
    )
    assert isinstance(adapter, LocalLlamaAdapter)
    assert adapter.model_path == model_file


def test_model_list_exposes_installed_id(tmp_path: Path):
    from shorts_engine.models.manager import ModelManager
    from shorts_engine.storage.db import Database
    from shorts_engine.storage.repos import ModelRepo

    db = Database(tmp_path / "models.sqlite3")
    manager = ModelManager(tmp_path / "models", ModelRepo(db))
    root = tmp_path / "models" / "whisper" / "tiny"
    root.mkdir(parents=True)
    (root / "model.bin").write_bytes(b"x")
    record = manager.repo.upsert("whisper", "tiny", str(root), version="t", sha256="x", bytes_=1, meta={})
    item = next(i for i in manager.list()["items"] if i["kind"] == "whisper" and i["name"] == "tiny")
    assert item["installed"] is True
    assert item["id"] == record["id"]
    db.close()
