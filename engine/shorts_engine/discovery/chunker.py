from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Window:
    index: int
    start_s: float
    end_s: float
    segments: list[dict[str, Any]]

    @property
    def start_key(self) -> str:
        return self.segments[0]["segKey"] if self.segments else ""

    @property
    def end_key(self) -> str:
        return self.segments[-1]["segKey"] if self.segments else ""


def build_windows(
    segments: list[dict[str, Any]],
    *,
    target_s: float = 360.0,
    overlap: float = 0.22,
) -> list[Window]:
    """Overlapping windows of roughly target_s seconds, aligned to segment boundaries."""
    if not segments:
        return []
    windows: list[Window] = []
    step = max(60.0, target_s * (1.0 - overlap))
    source_start = float(segments[0]["startS"])
    source_end = float(segments[-1]["endS"])
    start = source_start
    index = 0
    while start < source_end:
        end = start + target_s
        selected = [
            s for s in segments
            if float(s["startS"]) < end and float(s["endS"]) > start
        ]
        if selected and (not windows or selected[-1]["segKey"] != windows[-1].segments[-1]["segKey"]):
            windows.append(Window(index=index, start_s=start, end_s=min(end, source_end), segments=selected))
            index += 1
        if end >= source_end:
            break
        start += step
    return windows


def window_lines(window: Window) -> list[str]:
    from ..common.util import format_timecode

    return [
        f"[{s['segKey']}|{format_timecode(s['startS'], ms=False)}] {s['text']}"
        for s in window.segments
    ]


@dataclass
class WindowBatch:
    """One provider request covering one or more adjacent windows.

    Batching removes repeated system prompts and overlapping transcript text,
    which matters on token-per-minute plans. Each batch still references the
    original transcript segment IDs, so validation and boundary snapping are
    unchanged.
    """

    index: int
    start_s: float
    end_s: float
    segments: list[dict[str, Any]]
    source_windows: list[int]

    @property
    def start_key(self) -> str:
        return self.segments[0]["segKey"] if self.segments else ""

    @property
    def end_key(self) -> str:
        return self.segments[-1]["segKey"] if self.segments else ""


def batch_windows(windows: list[Window], *, size: int = 2) -> list[WindowBatch]:
    """Group adjacent windows, de-duplicating overlap, without changing ranges."""
    if not windows:
        return []
    size = max(1, int(size))
    batches: list[WindowBatch] = []
    for index, start in enumerate(range(0, len(windows), size)):
        group = windows[start : start + size]
        by_key: dict[str, dict[str, Any]] = {}
        for window in group:
            for segment in window.segments:
                by_key[segment["segKey"]] = segment
        segments = sorted(by_key.values(), key=lambda s: (float(s["startS"]), s["segKey"]))
        if not segments:
            continue
        batches.append(
            WindowBatch(
                index=index,
                start_s=float(group[0].start_s),
                end_s=float(group[-1].end_s),
                segments=segments,
                source_windows=[w.index for w in group],
            )
        )
    return batches
