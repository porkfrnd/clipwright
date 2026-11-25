from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Word:
    start_s: float
    end_s: float
    text: str
    confidence: float | None = None


@dataclass
class Segment:
    start_s: float
    end_s: float
    text: str
    words: list[Word] = field(default_factory=list)


@dataclass
class ParsedTranscript:
    language: str | None
    word_timing: str  # exact | approximate | none
    segments: list[Segment]
    origin: str
    engine: str
    model: str | None = None


def _ts(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(value)
    except ValueError:
        return 0.0


_TAG = re.compile(r"<[^>]+>")
_TS_TAG = re.compile(r"<(\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3})>")


def _clean_text(text: str) -> str:
    text = _TAG.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _distribute_words(text: str, start: float, end: float) -> list[Word]:
    tokens = [t for t in text.split() if t]
    if not tokens:
        return []
    duration = max(0.05, end - start)
    total_chars = sum(len(t) for t in tokens) or 1
    words: list[Word] = []
    cursor = start
    for token in tokens:
        share = duration * (len(token) / total_chars)
        words.append(Word(cursor, min(end, cursor + share), token))
        cursor += share
    if words:
        words[-1].end_s = end
    return words


def parse_vtt(text: str) -> ParsedTranscript:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    segments: list[Segment] = []
    any_exact = False
    seen = set()
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines or lines[0].strip().startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
            continue
        ts_line = next((ln for ln in lines if "-->" in ln), None)
        if not ts_line:
            continue
        left, right = ts_line.split("-->", 1)
        start = _ts(left.strip().split(" ")[0])
        end = _ts(right.strip().split(" ")[0])
        content_start = lines.index(ts_line) + 1
        content_lines = lines[content_start:]
        raw = "\n".join(content_lines)
        # Auto-caption timing tags: <00:00:01.234>
        markers = list(_TS_TAG.finditer(raw))
        if markers:
            any_exact = True
            words: list[Word] = []
            for i, marker in enumerate(markers):
                w_start = _ts(marker.group(1))
                w_end = _ts(markers[i + 1].group(1)) if i + 1 < len(markers) else end
                chunk = raw[marker.end(): markers[i + 1].start() if i + 1 < len(markers) else len(raw)]
                cleaned = _clean_text(chunk)
                if cleaned:
                    for token in cleaned.split():
                        words.append(Word(max(start, w_start), max(w_start, w_end), token))
            if words:
                plain = _clean_text(raw)
                key = (round(start, 2), plain)
                if key not in seen:
                    seen.add(key)
                    segments.append(Segment(start, end, plain, words))
            continue
        plain = _clean_text(raw)
        if not plain:
            continue
        key = (round(start, 2), plain)
        if key in seen:
            continue
        seen.add(key)
        words = _distribute_words(plain, start, end)
        segments.append(Segment(start, end, plain, words))
    segments.sort(key=lambda s: s.start_s)
    merged: list[Segment] = []
    for seg in segments:
        if merged and abs(seg.start_s - merged[-1].start_s) < 0.05 and seg.text == merged[-1].text:
            continue
        merged.append(seg)
    return ParsedTranscript(
        language=None,
        word_timing="exact" if any_exact else "approximate",
        segments=merged,
        origin="subtitle",
        engine="yt-dlp captions",
    )


def parse_json3(data: dict[str, Any]) -> ParsedTranscript:
    events = data.get("events") or []
    segments: list[Segment] = []
    any_word_offsets = False
    for event in events:
        if "segs" not in event:
            continue
        start = float(event.get("tStartMs", 0)) / 1000.0
        duration = float(event.get("dDurationMs", 0)) / 1000.0
        end = start + duration
        segs = event["segs"]
        words: list[Word] = []
        for seg in segs:
            chunk = (seg.get("utf8") or "").replace("\n", " ")
            if not chunk.strip():
                continue
            offset = seg.get("tOffsetMs")
            if offset is not None:
                any_word_offsets = True
                w_start = start + float(offset) / 1000.0
                w_end = start + float(seg.get("tOffsetMs", 0)) / 1000.0 + 0.0
                # json3 gives per-seg offsets, not durations; estimate by next offset below.
                words.append(Word(w_start, w_end, chunk.strip()))
                words[-1].confidence = None
            else:
                words.append(Word(start, end, chunk.strip()))
        text = "".join((s.get("utf8") or "") for s in segs).replace("\n", " ").strip()
        text = re.sub(r"\s+", " ", html.unescape(text))
        if not text:
            continue
        if any_word_offsets and words:
            for i, word in enumerate(words):
                word.end_s = words[i + 1].start_s if i + 1 < len(words) else end
                if word.end_s <= word.start_s:
                    word.end_s = min(end, word.start_s + 0.12)
            # Split multi-token segs into tokens, keeping proportional timing.
            expanded: list[Word] = []
            for word in words:
                tokens = word.text.split()
                if len(tokens) <= 1:
                    expanded.append(word)
                    continue
                span = max(0.05, word.end_s - word.start_s)
                total = sum(len(t) for t in tokens) or 1
                cursor = word.start_s
                for token in tokens:
                    share = span * (len(token) / total)
                    expanded.append(Word(cursor, min(word.end_s, cursor + share), token))
                    cursor += share
            words = expanded
        elif not words:
            words = _distribute_words(text, start, end)
        segments.append(Segment(start, end, text, words))
    return ParsedTranscript(
        language=None,
        word_timing="exact" if any_word_offsets else "approximate",
        segments=segments,
        origin="subtitle",
        engine="yt-dlp captions",
    )


def parse_verbose_json(data: dict[str, Any], *, language: str | None = None) -> ParsedTranscript:
    segments: list[Segment] = []
    has_words = False
    for item in data.get("segments") or []:
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        text = (item.get("text") or "").strip()
        words: list[Word] = []
        for w in item.get("words") or []:
            if w.get("word") is None:
                continue
            has_words = True
            words.append(
                Word(
                    float(w.get("start", start)),
                    float(w.get("end", end)),
                    str(w["word"]).strip(),
                    float(w["probability"]) if w.get("probability") is not None else None,
                )
            )
        if not words and text:
            words = _distribute_words(text, start, end)
        if text:
            segments.append(Segment(start, end, text, words))
    if not segments and data.get("text"):
        duration = 0.0
        for item in data.get("segments") or []:
            duration = max(duration, float(item.get("end", 0)))
        segments = [Segment(0.0, duration or 1.0, data["text"].strip(), [])]
    return ParsedTranscript(
        language=data.get("language") or language,
        word_timing="exact" if has_words else "approximate",
        segments=segments,
        origin="cloud",
        engine="openai-compatible",
    )


def parse_subtitle_file(path: Path) -> ParsedTranscript:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".json3" or raw.lstrip().startswith("{"):
        return parse_json3(json.loads(raw))
    if suffix in (".vtt", ".srt"):
        return parse_vtt(raw)
    return parse_vtt(raw)


def dedupe_segments(segments: list[Segment]) -> list[Segment]:
    """Remove YouTube caption rolling duplicates, keeping the longest version."""
    out: list[Segment] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        if out:
            prev = out[-1]
            if seg.text == prev.text:
                continue
            if seg.text.startswith(prev.text) and seg.start_s <= prev.end_s + 0.5:
                out[-1] = seg
                continue
            if prev.text.startswith(seg.text) and seg.start_s <= prev.end_s:
                continue
        out.append(seg)
    return out
