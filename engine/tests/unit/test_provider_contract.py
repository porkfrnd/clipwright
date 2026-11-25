import json

import pytest

from shorts_engine.ai.adapter import AdapterHooks, OpenAICompatibleAdapter
from shorts_engine.ai.schemas import CandidateProposal, Category
from shorts_engine.common.errors import EngineError


def test_candidate_schema_rejects_raw_timestamps_and_bad_segments():
    with pytest.raises(Exception):
        CandidateProposal.model_validate(
            {
                "category": "insight",
                "start_seg": "0:12",
                "end_seg": "s0002",
                "title": "x",
                "rationale": "y",
                "ratings": {
                    "hook_strength": {"score": 3},
                    "context_completeness": {"score": 3},
                    "ending_quality": {"score": 3},
                    "standalone_clarity": {"score": 3},
                },
            }
        )
    with pytest.raises(Exception):
        CandidateProposal.model_validate(
            {
                "category": "not-a-category",
                "start_seg": "s0000",
                "end_seg": "s0002",
                "title": "x",
                "rationale": "y",
                "ratings": {
                    "hook_strength": {"score": 3},
                    "context_completeness": {"score": 3},
                    "ending_quality": {"score": 3},
                    "standalone_clarity": {"score": 3},
                },
            }
        )


def test_candidate_schema_accepts_segment_references_and_fills_ratings():
    candidate = CandidateProposal.model_validate(
        {
            "category": "educational",
            "start_seg": "s0000",
            "end_seg": "s0003",
            "title": "A title",
            "rationale": "Because it lands.",
            "ratings": {
                "hook_strength": {"score": 4, "evidence": "Strong opening."},
                "context_completeness": {"score": 4},
                "ending_quality": {"score": 4},
                "standalone_clarity": {"score": 4},
            },
        }
    )
    assert candidate.start_seg == "s0000"
    assert candidate.category is Category.educational
    assert candidate.ratings.hook_strength.score == 4


@pytest.mark.asyncio
async def test_capability_probe_falls_back_from_schema_to_json_object(monkeypatch):
    adapter = OpenAICompatibleAdapter(base_url="http://stub.invalid/v1", api_key="test", model="m")
    calls: list[dict] = []

    async def fake_chat_raw(self, **kwargs):
        calls.append(kwargs)
        if kwargs["response_format"]["type"] == "json_schema":
            raise EngineError("PROVIDER_JSON_SCHEMA_UNSUPPORTED", "no schema")
        return type("Chat", (), {"text": '{"ok": true}', "total_tokens": 1})()

    monkeypatch.setattr(OpenAICompatibleAdapter, "_chat_raw", fake_chat_raw)
    caps = await adapter.probe_capabilities(AdapterHooks())
    assert [c["response_format"]["type"] for c in calls] == ["json_schema", "json_object"]
    assert caps.supports_json_schema is False
    assert caps.supports_json_object is True
    assert "JSON object" in (caps.probe_note or "")


@pytest.mark.asyncio
async def test_capability_probe_degrades_to_prompt_json(monkeypatch):
    adapter = OpenAICompatibleAdapter(base_url="http://stub.invalid/v1", api_key="test", model="m")
    calls = []

    async def fake_chat_raw(self, **kwargs):
        calls.append(kwargs)
        raise EngineError("PROVIDER_JSON_UNSUPPORTED", "no structured output")

    monkeypatch.setattr(OpenAICompatibleAdapter, "_chat_raw", fake_chat_raw)
    caps = await adapter.probe_capabilities(AdapterHooks())
    assert len(calls) == 2
    assert caps.supports_json_schema is False
    assert caps.supports_json_object is False
    assert "prompt-constrained" in (caps.probe_note or "")


@pytest.mark.asyncio
async def test_auth_failure_is_not_silently_degraded(monkeypatch):
    adapter = OpenAICompatibleAdapter(base_url="http://stub.invalid/v1", api_key="bad", model="m")

    async def fake_chat_raw(self, **kwargs):
        raise EngineError("PROVIDER_AUTH_FAILED", "bad key")

    monkeypatch.setattr(OpenAICompatibleAdapter, "_chat_raw", fake_chat_raw)
    with pytest.raises(EngineError) as info:
        await adapter.probe_capabilities(AdapterHooks())
    assert info.value.code == "PROVIDER_AUTH_FAILED"


def test_strip_json_handles_fences_and_preamble():
    from shorts_engine.ai.adapter import _strip_json

    assert json.loads(_strip_json('```json\n{"a": 1}\n```')) == {"a": 1}
    assert json.loads(_strip_json('Here is the JSON:\n{"a": 2}\nThanks')) == {"a": 2}


def test_segment_ids_accept_copied_prompt_labels_but_not_timestamps():
    from shorts_engine.ai.schemas import RankedItem

    candidate = CandidateProposal.model_validate(
        {
            "category": "insight",
            "start_seg": "s0001|00:00:06",
            "end_seg": "s0002|00:00:16",
            "title": "A clean title",
            "rationale": "This explains the point clearly.",
            "ratings": {
                "hook_strength": {"score": 4},
                "context_completeness": {"score": 4},
                "ending_quality": {"score": 4},
                "standalone_clarity": {"score": 4},
            },
        }
    )
    assert candidate.start_seg == "s0001"
    assert candidate.end_seg == "s0002"
    ranked = RankedItem.model_validate({"start_seg": "s0001|00:00:06", "end_seg": "s0002", "rank": 1})
    assert ranked.start_seg == "s0001"
    with pytest.raises(Exception):
        CandidateProposal.model_validate(
            {
                "category": "insight",
                "start_seg": "00:00:06",
                "end_seg": "s0002",
                "title": "A clean title",
                "rationale": "This explains the point clearly.",
                "ratings": {
                    "hook_strength": {"score": 4},
                    "context_completeness": {"score": 4},
                    "ending_quality": {"score": 4},
                    "standalone_clarity": {"score": 4},
                },
            }
        )
