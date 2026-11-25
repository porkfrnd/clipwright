from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from shorts_engine.transcription.base import TranscriptionOptions
from shorts_engine.transcription.local_whisper import LocalWhisperEngine

REPO = Path(__file__).resolve().parents[3]
MODEL_CANDIDATES = [
    Path(os.environ.get("CLIPWRIGHT_TEST_WHISPER_MODEL", "")) if os.environ.get("CLIPWRIGHT_TEST_WHISPER_MODEL") else None,
    Path("/tmp/cwtrans/models/whisper/tiny"),
    Path.home() / ".local/share/clipwright/models/whisper/tiny",
]


@pytest.mark.slow
@pytest.mark.asyncio
async def test_local_whisper_real_clip():
    model = next((p for p in MODEL_CANDIDATES if p and (p / "model.bin").exists()), None)
    if model is None:
        pytest.skip("tiny Whisper model not present; run Model Manager download first")
    audio = REPO / "tests/fixtures/src/s1.wav"
    assert audio.exists()
    progress: list[float] = []
    engine = LocalWhisperEngine(
        model,
        "tiny",
        device="cpu",
        compute_type="int8",
        ffmpeg_path="ffmpeg",
    )
    parsed = await engine.transcribe(
        audio,
        TranscriptionOptions(language="en", word_timestamps=True),
        duration_s=13.0,
        progress=lambda fraction, message: progress.append(fraction),
        cancel=asyncio.Event(),
    )
    assert parsed.segments, "real speech must produce segments"
    assert parsed.language == "en"
    assert parsed.engine == "faster-whisper"
    assert parsed.word_timing == "exact"
    text = " ".join(s.text for s in parsed.segments).lower()
    assert "welcome" in text
    starts = [s.start_s for s in parsed.segments]
    ends = [s.end_s for s in parsed.segments]
    assert starts == sorted(starts)
    assert all(e >= s for s, e in zip(starts, ends))
    assert parsed.segments[0].start_s < 1.5
    assert any(s.words for s in parsed.segments)
    assert progress and progress[-1] == 1.0
