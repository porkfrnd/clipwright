from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ai.schemas import CandidateProposal


@dataclass
class ValidationResult:
    valid: list[CandidateProposal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def validate_proposals(
    proposals: list[CandidateProposal],
    window_segments: list[dict[str, Any]],
    *,
    min_duration: float = 15.0,
    max_duration: float = 90.0,
    window_start: float | None = None,
    window_end: float | None = None,
    source_start: float = 0.0,
    source_end: float = 1e9,
) -> ValidationResult:
    """Reject anything the model could not legitimately know or that breaks the rules."""
    by_key = {s["segKey"]: i for i, s in enumerate(window_segments)}
    result = ValidationResult()
    if not window_segments:
        return result
    for proposal in proposals:
        start_i = by_key.get(proposal.start_seg)
        end_i = by_key.get(proposal.end_seg)
        if start_i is None or end_i is None:
            result.errors.append(f"Unknown segment id in {proposal.start_seg}-{proposal.end_seg}.")
            continue
        if end_i < start_i:
            result.errors.append(f"Reversed range {proposal.start_seg}-{proposal.end_seg}.")
            continue
        # A range touching a synthetic window edge may cut a sentence in half.
        if start_i == 0 and (window_start or 0) > source_start + 0.01:
            result.errors.append(f"{proposal.start_seg} touches the window start and may cut context.")
            continue
        if end_i == len(window_segments) - 1 and (window_end or 0) < source_end - 0.01:
            result.errors.append(f"{proposal.end_seg} touches the window end and may cut a sentence.")
            continue
        start_s = float(window_segments[start_i]["startS"])
        end_s = float(window_segments[end_i]["endS"])
        duration = end_s - start_s
        if duration < min_duration:
            result.errors.append(f"{proposal.start_seg}-{proposal.end_seg} is {duration:.1f}s, under {min_duration:.0f}s.")
            continue
        if duration > max_duration:
            result.errors.append(f"{proposal.start_seg}-{proposal.end_seg} is {duration:.1f}s, over {max_duration:.0f}s.")
            continue
        if not proposal.rationale.strip():
            result.errors.append("Missing rationale.")
            continue
        result.valid.append(proposal)
    return result


def proposals_to_dicts(proposals: list[CandidateProposal]) -> list[dict[str, Any]]:
    return [p.model_dump(mode="json") for p in proposals]


def dicts_to_proposals(items: list[dict[str, Any]]) -> list[CandidateProposal]:
    out = []
    for item in items:
        try:
            out.append(CandidateProposal.model_validate(item))
        except Exception:
            continue
    return out
