from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any


def iou(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def text_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def dedupe_candidates(
    candidates: list[dict[str, Any]],
    *,
    iou_threshold: float = 0.55,
    text_threshold: float = 0.82,
) -> list[dict[str, Any]]:
    """Merge near-duplicates, keeping the stronger candidate and unioning categories."""
    ranked = sorted(candidates, key=lambda c: c.get("fit_score", 0), reverse=True)
    kept: list[dict[str, Any]] = []
    for cand in ranked:
        duplicate = None
        for existing in kept:
            overlap = iou(cand["start_s"], cand["end_s"], existing["start_s"], existing["end_s"])
            similar = text_similarity(cand.get("excerpt", "") + cand["title"], existing.get("excerpt", "") + existing["title"])
            if overlap >= iou_threshold or similar >= text_threshold:
                duplicate = existing
                break
        if duplicate is None:
            kept.append(cand)
        else:
            cats = set(duplicate.get("categories") or [])
            cats.update(cand.get("categories") or [])
            duplicate["categories"] = sorted(cats)
    return kept
