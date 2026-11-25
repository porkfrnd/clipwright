from __future__ import annotations

from typing import Any

from ...render.timeline import plan_timeline
from ..params import TimelinePlanParams
from ..registry import Registry
from .captions import _context


def register(registry: Registry) -> None:
    registry.add("timeline.plan", TimelinePlanParams, plan)


async def plan(app, params: TimelinePlanParams, secrets) -> dict[str, Any]:
    _selection, candidate, _source, transcript, _edit = _context(app, params.selectionId)
    return {
        "selectionId": params.selectionId,
        "wordTiming": transcript.get("wordTiming") or "approximate",
        **plan_timeline(
            transcript.get("segments") or [],
            start_s=float(candidate["startS"]),
            end_s=float(candidate["endS"]),
            pause_threshold_s=params.pauseThresholdS,
            min_pause_s=params.minPauseS,
            remove_fillers=params.removeFillers,
            word_timing=transcript.get("wordTiming") or "approximate",
        ),
        "disclosure": "Local timing plan. The source file and transcript are never modified.",
    }
