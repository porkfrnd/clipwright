from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

MAX_CHARS_PER_LINE = 24


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB (+ optional alpha 0-255) to ASS &HAABBGGRR."""
    value = (hex_color or "#FFFFFF").lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    except (ValueError, IndexError):
        r, g, b = 255, 255, 255
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("\n", "\\N")
    )


@dataclass
class CaptionWord:
    start_s: float
    end_s: float
    text: str


@dataclass
class CaptionLine:
    start_s: float
    end_s: float
    words: list[CaptionWord]
    approximate: bool = False
    # Display rows. Two rows become one ASS event separated by \N.
    rows: list[list[CaptionWord]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _wrap_rows(words: list[CaptionWord], max_chars: int) -> list[list[CaptionWord]]:
    rows: list[list[CaptionWord]] = []
    current: list[CaptionWord] = []
    length = 0
    for word in words:
        addition = len(word.text) + (1 if current else 0)
        if current and length + addition > max_chars:
            rows.append(current)
            current = [word]
            length = len(word.text)
        else:
            current.append(word)
            length += addition
    if current:
        rows.append(current)
    return rows


def build_caption_lines(
    segments: list[dict[str, Any]],
    *,
    start_s: float,
    end_s: float,
    max_lines: int = 2,
    uppercase: bool = True,
    word_timing: str = "exact",
) -> list[CaptionLine]:
    """Build subtitle lines clipped to a clip. Never invents words."""
    words: list[CaptionWord] = []
    for seg in segments:
        seg_start = float(seg["startS"] if "startS" in seg else seg["start_s"])
        seg_end = float(seg["endS"] if "endS" in seg else seg["end_s"])
        if seg_end <= start_s or seg_start >= end_s:
            continue
        seg_words = seg.get("words") or []
        source_words = seg_words or [{"text": seg["text"], "startS": seg_start, "endS": seg_end}]
        for w in source_words:
            w_start = float(w.get("startS", w.get("start_s", seg_start)))
            w_end = float(w.get("endS", w.get("end_s", seg_end)))
            if w_end <= start_s or w_start >= end_s:
                continue
            text = str(w.get("text", "")).strip()
            if not text:
                continue
            text = text.upper() if uppercase else text
            words.append(
                CaptionWord(
                    start_s=max(start_s, w_start),
                    end_s=min(end_s, w_end),
                    text=text,
                )
            )
    if not words:
        return []
    words.sort(key=lambda w: w.start_s)
    # Group words into short physical rows, then combine at most max_lines rows
    # into one caption event. ASS WrapStyle 2 does not auto-wrap, so the row
    # split has to be explicit or long captions run outside the video frame.
    rows = _wrap_rows(words, MAX_CHARS_PER_LINE)
    lines: list[CaptionLine] = []
    for start in range(0, len(rows), max(1, max_lines)):
        group_rows = rows[start:start + max(1, max_lines)]
        flat = [w for row in group_rows for w in row]
        if not flat:
            continue
        lines.append(
            CaptionLine(
                start_s=flat[0].start_s,
                end_s=flat[-1].end_s,
                words=flat,
                approximate=word_timing != "exact",
                rows=group_rows,
            )
        )
    # Merge very short groups with neighbours so captions do not flicker.
    merged: list[CaptionLine] = []
    for line in lines:
        if (
            merged
            and line.end_s - line.start_s < 0.45
            and len(merged[-1].rows) + len(line.rows) <= max(1, max_lines)
        ):
            merged[-1].words.extend(line.words)
            merged[-1].rows.extend(line.rows)
            merged[-1].end_s = line.end_s
            merged[-1].approximate = merged[-1].approximate or line.approximate
        else:
            merged.append(line)
    return merged


def build_ass(
    *,
    segments: list[dict[str, Any]],
    start_s: float,
    end_s: float,
    style: dict[str, Any],
    word_timing: str = "exact",
    offset_ms: float = 0.0,
    line_offsets_ms: dict[str, float] | None = None,
) -> str:
    font = style.get("font") or "Bebas Neue"
    font_size = int(style.get("fontSize") or 64)
    color = ass_color(style.get("color") or "#FFFFFF")
    highlight = ass_color(style.get("highlightColor") or "#E8C77B")
    outline_color = ass_color(style.get("outlineColor") or "#0B0910")
    outline = float(style.get("outline", 4))
    shadow = float(style.get("shadow", 1))
    background = bool(style.get("background", False))
    border_style = 3 if background else 1
    back_color = ass_color("#000000", 0x66) if background else ass_color("#000000", 0xFF)
    alignment = 2
    margin_v = 330 if style.get("position", "lower_third") == "lower_third" else 190
    if style.get("position") == "center":
        alignment, margin_v = 5, 0
    uppercase = bool(style.get("uppercase", True))
    max_lines = int(style.get("maxLines", 2))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Clip,{font},{font_size},{color},{highlight},{outline_color},{back_color},-1,0,0,0,100,100,0.6,0,{border_style},{outline},{shadow},{alignment},72,72,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = build_caption_lines(
        segments,
        start_s=start_s,
        end_s=end_s,
        max_lines=max_lines,
        uppercase=uppercase,
        word_timing=word_timing,
    )
    line_offsets_ms = line_offsets_ms or {}
    events: list[str] = []
    for line in lines:
        rows = line.rows or [line.words]
        # A per-line nudge is additive to the global sync offset. Keys are the
        # line's original source start in milliseconds, stable across edits.
        line_key = f"{int(round(line.start_s * 1000))}"
        shift_s = (offset_ms + float(line_offsets_ms.get(line_key, 0.0))) / 1000.0
        line_start = max(start_s, line.start_s + shift_s)
        line_end = min(end_s, max(line_start + 0.05, line.end_s + shift_s))
        if line.approximate:
            # Phrase-level highlight when word timing is not reliable.
            text = "\\N".join(" ".join(_escape(w.text) for w in row) for row in rows)
            events.append(
                f"Dialogue: 0,{ass_time(line_start - start_s)},{ass_time(line_end - start_s)},"
                f"Clip,,0,0,0,,{{\\c{highlight}}}{text}"
            )
            continue
        for index, word in enumerate(line.words):
            word_start = max(line_start, word.start_s + shift_s)
            word_end = (
                line.words[index + 1].start_s + shift_s if index + 1 < len(line.words) else line_end
            )
            if word_end - word_start < 0.03:
                word_end = word_start + 0.10
            pieces: list[str] = []
            flat_index = 0
            for row_index, row in enumerate(rows):
                if row_index:
                    pieces.append("\\N")
                row_pieces: list[str] = []
                for other in row:
                    escaped = _escape(other.text)
                    if flat_index == index:
                        row_pieces.append(f"{{\\c{highlight}}}{escaped}{{\\c{color}}}")
                    else:
                        row_pieces.append(escaped)
                    flat_index += 1
                pieces.append(" ".join(row_pieces))
            text = "".join(pieces)
            events.append(
                f"Dialogue: 0,{ass_time(word_start - start_s)},{ass_time(min(line_end, word_end) - start_s)},"
                f"Clip,,0,0,0,,{text}"
            )
    return header + "\n".join(events) + "\n"


def write_ass(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def escape_filter_path(path: Path) -> str:
    """Escape a path for use inside an ffmpeg filter argument."""
    value = str(path).replace("\\", "/")
    value = value.replace(":", "\\:")
    value = value.replace("'", "\\'")
    return value
