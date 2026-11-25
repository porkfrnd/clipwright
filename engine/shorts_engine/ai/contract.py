from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..common.util import format_timecode
from .adapter import AdapterHooks, ChatResult, OpenAICompatibleAdapter
from .prompts import SYSTEM_MAP, SYSTEM_METADATA, SYSTEM_RANK, map_prompt, metadata_prompt, rank_prompt
from .schemas import ClipMetadata, RankedCandidates, WindowAnalysis


@dataclass
class MomentWindow:
    start_s: float
    end_s: float
    lines: list[str]
    start_key: str
    end_key: str


def format_segments(segments: list[dict[str, Any]], *, show_end: bool = False) -> list[str]:
    lines = []
    for seg in segments:
        stamp = format_timecode(seg["startS"] if "startS" in seg else seg["start_s"], ms=False)
        lines.append(f"[{seg.get('segKey') or seg.get('seg_key')}|{stamp}] {seg['text']}")
    return lines


class MomentAI:
    """The application-level AI contract. Discovery depends only on this class."""

    def __init__(self, adapter: OpenAICompatibleAdapter) -> None:
        self.adapter = adapter

    async def find_moments(
        self,
        window: MomentWindow,
        *,
        title: str,
        max_candidates: int,
        hooks: AdapterHooks | None = None,
        note: str = "",
    ) -> tuple[WindowAnalysis, ChatResult]:
        prompt = map_prompt(
            title=title,
            window_start=format_timecode(window.start_s, ms=False),
            window_end=format_timecode(window.end_s, ms=False),
            transcript="\n".join(window.lines),
            max_candidates=max_candidates,
        )
        if note:
            prompt += "\n\nA previous answer was rejected by validation. Fix these problems:\n" + note
        result = await self.adapter.chat_structured(
            schema_model=WindowAnalysis,
            system=SYSTEM_MAP,
            user=prompt,
            operation="find_moments",
            hooks=hooks,
            max_tokens=min(self.adapter.capabilities.max_output_tokens, 6000),
        )
        return result.parsed, result  # type: ignore[return-value]

    async def rank_candidates(
        self,
        *,
        title: str,
        summaries: list[str],
        hooks: AdapterHooks | None = None,
    ) -> tuple[RankedCandidates, ChatResult]:
        result = await self.adapter.chat_structured(
            schema_model=RankedCandidates,
            system=SYSTEM_RANK,
            user=rank_prompt(title=title, candidates=summaries),
            operation="rank_candidates",
            hooks=hooks,
            max_tokens=min(self.adapter.capabilities.max_output_tokens, 2500),
            temperature=0.1,
        )
        return result.parsed, result  # type: ignore[return-value]

    async def generate_metadata(
        self,
        *,
        title: str,
        duration: float,
        source_title: str,
        transcript: str,
        hooks: AdapterHooks | None = None,
    ) -> tuple[ClipMetadata, ChatResult]:
        result = await self.adapter.chat_structured(
            schema_model=ClipMetadata,
            system=SYSTEM_METADATA,
            user=metadata_prompt(
                title=title, duration=duration, source_title=source_title, transcript=transcript
            ),
            operation="metadata",
            hooks=hooks,
            max_tokens=min(self.adapter.capabilities.max_output_tokens, 1600),
            temperature=0.6,
        )
        return result.parsed, result  # type: ignore[return-value]
