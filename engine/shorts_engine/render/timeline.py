from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

FILLERS = {"um", "uh", "erm", "hmm", "mm", "mhm"}


@dataclass(frozen=True)
class Cut:
    start_s: float
    end_s: float
    kind: str
    text: str = ""

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


def _words(segments: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for segment in segments:
        for word in segment.get("words") or []:
            word_start = float(word.get("startS", word.get("start_s", segment.get("startS", 0))))
            word_end = float(word.get("endS", word.get("end_s", word_start)))
            text = str(word.get("text", "")).strip()
            if not text or word_end <= start or word_start >= end:
                continue
            items.append({"startS": word_start, "endS": word_end, "text": text})
    items.sort(key=lambda item: item["startS"])
    return items


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def coerce_cuts(cuts: Iterable[Cut | dict[str, Any]]) -> list[Cut]:
    out: list[Cut] = []
    for cut in cuts:
        if isinstance(cut, Cut):
            out.append(cut)
        else:
            out.append(Cut(float(cut["startS"]), float(cut["endS"]), str(cut.get("kind") or "pause"), str(cut.get("text") or "")))
    return out


def _merge(cuts: Iterable[Cut]) -> list[Cut]:
    ordered = sorted(cuts, key=lambda cut: cut.start_s)
    merged: list[Cut] = []
    for cut in ordered:
        if cut.duration_s <= 0.02:
            continue
        if merged and cut.start_s <= merged[-1].end_s + 0.01:
            previous = merged[-1]
            merged[-1] = Cut(previous.start_s, max(previous.end_s, cut.end_s), previous.kind, previous.text or cut.text)
        else:
            merged.append(cut)
    return merged


def _keep_ranges(start: float, end: float, cuts: list[Cut]) -> list[tuple[float, float]]:
    ranges: list[tuple[float, float]] = []
    cursor = start
    for cut in cuts:
        left = max(start, min(end, cut.start_s))
        right = max(start, min(end, cut.end_s))
        if right <= cursor:
            continue
        if left > cursor:
            ranges.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < end:
        ranges.append((cursor, end))
    return [(a, b) for a, b in ranges if b - a > 0.02]


def map_time(time_s: float, *, start_s: float, cuts: list[Cut] | list[dict[str, Any]]) -> float:
    """Map a source time to the shortened output timeline."""
    cuts = coerce_cuts(cuts)
    output = 0.0
    cursor = start_s
    for cut in cuts:
        if time_s <= cut.start_s:
            return output + max(0.0, time_s - cursor)
        output += max(0.0, cut.start_s - cursor)
        if time_s < cut.end_s:
            # A time inside a removed span collapses onto the cut point.
            return output
        cursor = max(cursor, cut.end_s)
    return output + max(0.0, time_s - cursor)


def remap_segments(
    segments: list[dict[str, Any]],
    *,
    start_s: float,
    end_s: float,
    cuts: list[Cut] | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rewrite a transcript onto the shortened timeline, dropping cut words."""
    cuts = coerce_cuts(cuts)
    out: list[dict[str, Any]] = []
    for segment in segments:
        words: list[dict[str, Any]] = []
        for word in _words([segment], start_s, end_s):
            cut = next((c for c in cuts if word["endS"] > c.start_s and word["startS"] < c.end_s), None)
            if cut and cut.kind == "filler":
                continue
            mapped_start = map_time(word["startS"], start_s=start_s, cuts=cuts)
            mapped_end = map_time(word["endS"], start_s=start_s, cuts=cuts)
            if mapped_end - mapped_start < 0.03:
                continue
            words.append(
                {
                    "startS": round(mapped_start, 3),
                    "endS": round(mapped_end, 3),
                    "text": word["text"],
                }
            )
        if not words:
            continue
        out.append(
            {
                "startS": words[0]["startS"],
                "endS": words[-1]["endS"],
                "text": " ".join(word["text"] for word in words),
                "words": words,
            }
        )
    return out


def plan_timeline(
    segments: list[dict[str, Any]],
    *,
    start_s: float,
    end_s: float,
    pause_threshold_s: float = 0.6,
    min_pause_s: float = 0.25,
    remove_fillers: bool = False,
    word_timing: str = "exact",
) -> dict[str, Any]:
    duration = max(0.0, end_s - start_s)
    if word_timing != "exact":
        return {
            "supported": False,
            "reason": "This transcript has phrase-level timing, so pauses cannot be cut without guessing.",
            "originalDurationS": round(duration, 3),
            "plannedDurationS": round(duration, 3),
            "removedS": 0.0,
            "cuts": [],
            "pauses": [],
            "fillers": [],
        }
    words = _words(segments, start_s, end_s)
    if len(words) < 2:
        return {
            "supported": False,
            "reason": "Not enough word timing in this clip to detect pauses.",
            "originalDurationS": round(duration, 3),
            "plannedDurationS": round(duration, 3),
            "removedS": 0.0,
            "cuts": [],
            "pauses": [],
            "fillers": [],
        }

    cuts: list[Cut] = []
    pauses: list[dict[str, Any]] = []
    for previous, following in zip(words, words[1:]):
        gap = following["startS"] - previous["endS"]
        if gap < pause_threshold_s:
            continue
        # Leave a little breath on both sides so cuts land in silence, never on
        # a consonant. The removed span is the middle of the gap.
        pad = min(0.12, max(0.04, gap * 0.18))
        cut_start = previous["endS"] + pad
        cut_end = following["startS"] - pad
        if cut_end - cut_start < min_pause_s:
            continue
        keep = max(min_pause_s, gap - 2 * pad)
        cuts.append(Cut(cut_start, cut_end, "pause", f"{previous['text']} … {following['text']}"))
        pauses.append(
            {
                "startS": round(cut_start, 3),
                "endS": round(cut_end, 3),
                "durationS": round(cut_end - cut_start, 3),
                "keptS": round(keep, 3),
                "context": f"{previous['text']} … {following['text']}",
            }
        )

    fillers: list[dict[str, Any]] = []
    if remove_fillers:
        for word in words:
            if _normalise(word["text"]) not in FILLERS:
                continue
            if word["endS"] - word["startS"] < 0.04:
                continue
            # A filler is removed with a tiny pad, then merged with adjacent
            # pause cuts so we never emit overlapping ranges.
            cuts.append(Cut(word["startS"], word["endS"], "filler", word["text"]))
            fillers.append(
                {
                    "startS": round(word["startS"], 3),
                    "endS": round(word["endS"], 3),
                    "text": word["text"],
                }
            )

    merged = _merge(cuts)
    removed = sum(cut.duration_s for cut in merged)
    keep = _keep_ranges(start_s, end_s, merged)
    planned = max(0.2, duration - removed)
    return {
        "supported": bool(merged),
        "reason": None if merged else "No removable pauses were found at this threshold.",
        "originalDurationS": round(duration, 3),
        "plannedDurationS": round(planned, 3),
        "removedS": round(removed, 3),
        "cuts": [
            {"startS": round(cut.start_s, 3), "endS": round(cut.end_s, 3), "kind": cut.kind, "text": cut.text}
            for cut in merged
        ],
        "pauses": pauses,
        "fillers": fillers,
        "keepRanges": [{"startS": round(a, 3), "endS": round(b, 3)} for a, b in keep],
    }
