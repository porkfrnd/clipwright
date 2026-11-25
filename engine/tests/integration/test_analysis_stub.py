from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from shorts_engine.ai.adapter import OpenAICompatibleAdapter
from shorts_engine.ai.schemas import ProviderCapabilities
from shorts_engine.api.context import build_context
from shorts_engine.common.paths import AppPaths
from shorts_engine.discovery.pipeline import AnalysisHooks, AnalysisOptions, DiscoveryPipeline

REPO = Path(__file__).resolve().parents[3]
sys_path = REPO / "tests" / "fixtures"
import sys

sys.path.insert(0, str(sys_path))
from stub_server import StubServer  # noqa: E402


def seed(engine_dir: Path):
    ctx = build_context(AppPaths(engine_dir))
    ctx.settings.set("privacy", {"requestLogEnabled": True})
    project = ctx.projects.create("Stub analysis")
    source = ctx.sources.create(
        project["id"],
        kind="file",
        local_path=str(REPO / "tests/fixtures/demo-lecture.mp4"),
        title="Synthetic lecture",
        duration_s=60.0,
        authorization_ack_at="2026-01-01T00:00:00Z",
    )
    segments = []
    texts = [
        "Welcome to this test of the clip finding engine.",
        "Today we talk about how small moments become memorable stories.",
        "The first lesson is simple. Start with a question that makes people curious.",
        "Then explain the answer in plain language. Do not hide the answer behind jargon.",
        "Finally, close on a line people can repeat. That is what makes a clip travel.",
    ]
    cursor = 0.8
    for index, text in enumerate(texts):
        words = []
        tokens = text.split()
        word_cursor = cursor
        for token in tokens:
            words.append(
                {"seq": len(words), "start_s": round(word_cursor, 2), "end_s": round(word_cursor + 0.62, 2), "text": token}
            )
            word_cursor += 0.7
        end = round(word_cursor - 0.08, 2)
        segments.append(
            {
                "seq": index,
                "seg_key": f"s{index:04d}",
                "start_s": round(cursor, 2),
                "end_s": end,
                "text": text,
                "words": words,
            }
        )
        cursor = end + 0.5
    transcript = ctx.transcripts.save(
        source["id"],
        origin="local_whisper",
        engine="local_whisper",
        model="tiny",
        language="en",
        params={},
        cache_key="stub-analysis",
        word_timing="exact",
        segments=segments,
    )
    return ctx, source, transcript


@pytest.mark.asyncio
async def test_analysis_pipeline_with_stub_provider(tmp_path: Path):
    ctx, source, transcript = seed(tmp_path / "engine")
    with StubServer() as stub:
        adapter = OpenAICompatibleAdapter(
            base_url=stub.base_url,
            api_key="stub-key",
            model="stub-model",
            capabilities=ProviderCapabilities(
                supports_json_schema=True,
                supports_json_schema_strict=True,
                supports_json_object=True,
                context_tokens=131072,
            ),
        )
        pipeline = DiscoveryPipeline(
            runs=ctx.runs, candidates=ctx.candidates, transcripts=ctx.transcripts, sources=ctx.sources
        )
        progress: list[tuple[str, float]] = []
        states: list[str] = []
        checkpoints: list[dict] = []
        hooks = AnalysisHooks(
            progress=lambda stage, fraction, message: progress.append((stage, fraction)),
            state=lambda state: states.append(state),
            checkpoint=lambda data: checkpoints.append(dict(data)),
            request_log=lambda *args: None,
        )
        result = await pipeline.run(
            source=source,
            transcript=transcript,
            adapter=adapter,
            provider_profile_id="stub-provider",
            model="stub-model",
            options=AnalysisOptions(min_duration=15, max_duration=90, max_candidates_per_window=5),
            hooks=hooks,
        )

    assert result["candidateCount"] >= 1
    assert result["analysisRunId"]
    assert checkpoints, "analysis must persist resumable checkpoints"
    assert any(stage == "finding_moments" for stage, _ in progress)
    listed = ctx.candidates.list(source["id"])
    assert len(listed) >= 1
    for candidate in listed:
        assert re.fullmatch(r"s\d{4,6}", candidate["segStartKey"])
        assert re.fullmatch(r"s\d{4,6}", candidate["segEndKey"])
        assert 15 <= candidate["endS"] - candidate["startS"] <= 90.0001
        assert candidate["fitScore"] >= 0
        assert candidate["ratings"]
        assert candidate["rationale"]
        assert candidate["excerpt"]
        assert candidate["categories"]
    assert any("best_overall" in c["categories"] for c in listed)
    runs = ctx.runs.list(source["id"])
    assert runs[0]["state"] == "succeeded"
    assert runs[0]["tokenUsage"]["totalTokens"] > 0
    ctx.db.close()


@pytest.mark.asyncio
async def test_rate_limit_wait_then_resume_without_losing_work(tmp_path: Path):
    ctx, source, transcript = seed(tmp_path / "engine")
    with StubServer(rate_limit_once=True) as stub:
        adapter = OpenAICompatibleAdapter(
            base_url=stub.base_url,
            api_key="stub-key",
            model="stub-model",
            capabilities=ProviderCapabilities(supports_json_schema=True, supports_json_object=True),
        )
        pipeline = DiscoveryPipeline(
            runs=ctx.runs, candidates=ctx.candidates, transcripts=ctx.transcripts, sources=ctx.sources
        )
        states: list[str] = []
        waits: list[tuple[float, str]] = []

        async def wait(seconds: float, reason: str) -> None:
            waits.append((seconds, reason))

        hooks = AnalysisHooks(
            state=lambda state: states.append(state),
            wait=wait,
            request_log=lambda *args: None,
        )
        result = await pipeline.run(
            source=source,
            transcript=transcript,
            adapter=adapter,
            provider_profile_id="stub-provider",
            model="stub-model",
            options=AnalysisOptions(min_duration=15, max_duration=90),
            hooks=hooks,
        )
    assert waits and waits[0][1]
    assert "waiting_rate_limit" in states
    assert result["candidateCount"] >= 1
    assert len(stub.state.requests) >= 2
    ctx.db.close()


@pytest.mark.asyncio
async def test_cancel_stops_before_calling_provider(tmp_path: Path):
    ctx, source, transcript = seed(tmp_path / "engine")
    cancel = asyncio.Event()
    cancel.set()
    with StubServer() as stub:
        adapter = OpenAICompatibleAdapter(
            base_url=stub.base_url,
            api_key="stub-key",
            model="stub-model",
            capabilities=ProviderCapabilities(supports_json_schema=True),
        )
        pipeline = DiscoveryPipeline(
            runs=ctx.runs, candidates=ctx.candidates, transcripts=ctx.transcripts, sources=ctx.sources
        )
        hooks = AnalysisHooks(cancel=cancel)
        with pytest.raises(Exception) as info:
            await pipeline.run(
                source=source,
                transcript=transcript,
                adapter=adapter,
                provider_profile_id="stub-provider",
                model="stub-model",
                options=AnalysisOptions(min_duration=15, max_duration=90),
                hooks=hooks,
            )
        assert "CANCELLED" in str(getattr(info.value, "code", "")).upper()
        assert stub.state.requests == []
    ctx.db.close()
