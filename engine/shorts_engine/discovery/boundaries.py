from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TERMINAL = re.compile(r"[.!?…][\"'”’)\]]*\s*$")


@dataclass
class BoundaryResult:
    start_s: float
    end_s: float
    signals: dict[str, Any]

    @property
    def duration(self) -> float:
        return self.end_s - self.start_s


def _flatten_words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for seg_index, seg in enumerate(segments):
        seg_words = seg.get("words") or []
        if seg_words:
            for word in seg_words:
                words.append(
                    {
                        "start": float(word["startS"]),
                        "end": float(word["endS"]),
                        "text": word["text"],
                        "seg": seg_index,
                    }
                )
        else:
            # Fall back to segment timing when no word timing exists.
            tokens = [t for t in seg["text"].split() if t]
            if tokens:
                span = max(0.05, float(seg["endS"]) - float(seg["startS"]))
                total = sum(len(t) for t in tokens) or 1
                cursor = float(seg["startS"])
                for token in tokens:
                    share = span * len(token) / total
                    words.append(
                        {
                            "start": cursor,
                            "end": min(float(seg["endS"]), cursor + share),
                            "text": token,
                            "seg": seg_index,
                        }
                    )
                    cursor += share
    words.sort(key=lambda w: (w["start"], w["end"]))
    return words


def _snap_to_words(
    words: list[dict[str, Any]], start_s: float, end_s: float
) -> tuple[float, float]:
    if not words:
        return start_s, end_s
    start = start_s
    for word in words:
        if word["end"] > start_s + 0.02:
            start = word["start"]
            break
    else:
        start = words[-1]["start"]
    end = end_s
    for word in reversed(words):
        if word["start"] < end_s - 0.02:
            end = word["end"]
            break
    else:
        end = words[0]["end"]
    if end <= start:
        end = min(start + 0.4, words[-1]["end"])
    return start, end


def _sentence_end(
    segments: list[dict[str, Any]], end_s: float, *, max_end: float
) -> tuple[float, bool]:
    """Return (end, ended_on_sentence_boundary). Extends to a terminal punctuation or pause."""
    if not segments:
        return end_s, False
    index = 0
    for i, seg in enumerate(segments):
        if float(seg["startS"]) <= end_s + 0.01:
            index = i
        else:
            break
    seg = segments[index]
    text = seg["text"].strip()
    seg_end = float(seg["endS"])
    has_terminal = bool(TERMINAL.search(text))
    next_gap = None
    if index + 1 < len(segments):
        next_gap = float(segments[index + 1]["startS"]) - seg_end
    if has_terminal:
        return min(max(seg_end, end_s), max_end), True
    if next_gap is not None and next_gap >= 0.35:
        return min(max(seg_end, end_s), max_end), True
    # Extend through up to three following segments to finish the thought.
    end = seg_end
    for j in range(index + 1, min(index + 4, len(segments))):
        nxt = segments[j]
        gap = float(nxt["startS"]) - float(segments[j - 1]["endS"])
        if gap > 0.6:
            break
        if float(nxt["endS"]) > max_end:
            break
        end = float(nxt["endS"])
        if TERMINAL.search(nxt["text"].strip()):
            return end, True
        if j + 1 < len(segments):
            pause = float(segments[j + 1]["startS"]) - float(nxt["endS"])
            if pause >= 0.35:
                return end, True
    return min(max(seg_end, end_s), max_end), False


def refine_boundaries(
    *,
    start_s: float,
    end_s: float,
    segments: list[dict[str, Any]],
    min_duration: float = 15.0,
    max_duration: float = 90.0,
    lead_pad: float = 0.15,
    tail_pad: float = 0.30,
    source_end: float | None = None,
) -> BoundaryResult | None:
    """Snap to words, finish the sentence, pad, and enforce duration limits."""
    if not segments:
        return None
    source_end = source_end or float(segments[-1]["endS"])
    start_s = max(0.0, min(start_s, source_end))
    end_s = max(start_s, min(end_s, source_end))
    words = _flatten_words(segments)
    start, end = _snap_to_words(words, start_s, end_s)

    # Make sure the start does not land in the middle of a spoken word.
    for word in words:
        if word["start"] < start < word["end"]:
            start = word["start"]
            break

    end, sentence_aligned = _sentence_end(segments, end, max_end=source_end)

    # If the clip is too long, cut at the last sentence/word boundary before the cap.
    if end - start > max_duration:
        cap = start + max_duration
        candidate_end = end
        for seg in segments:
            seg_end = float(seg["endS"])
            if start < seg_end <= cap and (TERMINAL.search(seg["text"].strip())):
                candidate_end = seg_end
        for word in reversed(words):
            if start < word["end"] <= cap:
                candidate_end = word["end"]
                break
        end = min(end, max(candidate_end, start + min_duration))
        sentence_aligned = bool(
            any(abs(float(s["endS"]) - end) < 0.02 and TERMINAL.search(s["text"].strip()) for s in segments)
        )

    # If the clip is too short, extend to following words/segments when possible.
    if end - start < min_duration:
        cap = min(source_end, start + max_duration)
        for seg in segments:
            if float(seg["startS"]) >= end - 0.01 and float(seg["endS"]) <= cap:
                end = float(seg["endS"])
                if end - start >= min_duration and TERMINAL.search(seg["text"].strip()):
                    sentence_aligned = True
                    break
        if end - start < min_duration:
            for word in words:
                if word["start"] >= end - 0.01 and word["start"] <= cap:
                    end = word["end"]
                    if end - start >= min_duration:
                        break

    if end - start < min_duration or end - start > max_duration:
        return None

    # Small pads, never crossing into another word.
    padded_start = max(0.0, start - lead_pad)
    padded_end = min(source_end, end + tail_pad)
    if padded_end - padded_start > max_duration:
        padded_end = padded_start + max_duration

    voiced = 0.0
    word_count = 0
    for word in words:
        overlap = min(padded_end, word["end"]) - max(padded_start, word["start"])
        if overlap > 0:
            voiced += overlap
            word_count += 1
    duration = max(0.01, padded_end - padded_start)
    continuity = max(0.0, min(1.0, voiced / duration))
    if 20.0 <= duration <= 60.0:
        duration_fit = 1.0
    elif duration < 20.0:
        duration_fit = max(0.0, 0.55 + 0.45 * (duration - min_duration) / max(0.01, 20.0 - min_duration))
    else:
        duration_fit = max(0.0, 1.0 - 0.5 * (duration - 60.0) / max(0.01, max_duration - 60.0))
    return BoundaryResult(
        start_s=round(padded_start, 3),
        end_s=round(padded_end, 3),
        signals={
            "sentenceAlignedStart": True,
            "sentenceAlignedEnd": sentence_aligned,
            "durationFit": round(duration_fit, 3),
            "speechContinuity": round(continuity, 3),
            "wordCount": word_count,
            "durationS": round(duration, 3),
        },
    )
