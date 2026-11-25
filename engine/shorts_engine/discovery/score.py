from __future__ import annotations

from typing import Any

# Documented Clip fit formula. This is a fit-for-purpose score, not a prediction.
RATING_WEIGHTS = {
    "hook_strength": 0.32,
    "context_completeness": 0.24,
    "ending_quality": 0.20,
    "standalone_clarity": 0.24,
}
SIGNAL_WEIGHTS = {
    "boundaries": 0.25,
    "duration": 0.12,
    "continuity": 0.08,
}
RATING_WEIGHT_TOTAL = 0.55


def clip_fit(ratings: dict[str, Any], signals: dict[str, Any]) -> float:
    """0-100. 55% ordinal ratings, 25% boundaries, 12% duration, 8% speech continuity."""
    values = []
    for key, weight in RATING_WEIGHTS.items():
        rating = ratings.get(key) or {}
        score = rating.get("score") if isinstance(rating, dict) else None
        if not isinstance(score, (int, float)):
            score = 3
        values.append(weight * max(1.0, min(5.0, float(score))))
    rating_component = sum(values)  # 1..5
    rating_norm = (rating_component - 1.0) / 4.0
    aligned = (float(bool(signals.get("sentenceAlignedStart"))) + float(bool(signals.get("sentenceAlignedEnd")))) / 2
    duration_fit = float(signals.get("durationFit") or 0.0)
    continuity = float(signals.get("speechContinuity") or 0.0)
    signal_component = (
        SIGNAL_WEIGHTS["boundaries"] * aligned
        + SIGNAL_WEIGHTS["duration"] * duration_fit
        + SIGNAL_WEIGHTS["continuity"] * continuity
    ) / sum(SIGNAL_WEIGHTS.values())
    raw = RATING_WEIGHT_TOTAL * rating_norm + (1 - RATING_WEIGHT_TOTAL) * signal_component
    return round(max(0.0, min(1.0, raw)) * 100, 1)


def fit_explanation() -> str:
    return (
        "Clip fit combines the four ratings (55%) with sentence-aligned boundaries (25% of the "
        "remaining 45%), duration fit (12%) and speech continuity (8%). It is not a prediction "
        "of views or engagement."
    )
