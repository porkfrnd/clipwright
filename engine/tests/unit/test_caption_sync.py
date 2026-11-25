from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from shorts_engine.transcription.sync import estimate_offset


def _wav(onsets: list[float], duration: float = 6.0, rate: int = 16000) -> bytes:
    samples = np.zeros(int(duration * rate), dtype=np.float32)
    rng = np.random.default_rng(7)
    for onset in onsets:
        start = int(onset * rate)
        length = int(0.18 * rate)
        envelope = np.hanning(length).astype(np.float32)
        samples[start : start + length] += rng.standard_normal(length).astype(np.float32) * envelope * 0.35
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def test_estimates_known_global_shift():
    true_onsets = [0.8, 1.7, 2.6, 3.5, 4.4]
    # Subtitle times are 120 ms late relative to the spoken onsets.
    subtitle_times = [time - 0.120 for time in true_onsets]
    result = estimate_offset(_wav(true_onsets), subtitle_times)
    assert result["confidence"] == "High"
    assert abs(result["offsetMs"] - 120) <= 20
    assert result["wordsUsed"] == len(true_onsets)


def test_sparse_speech_refuses_to_guess():
    result = estimate_offset(_wav([1.0]), [1.0])
    assert result["offsetMs"] == 0
    assert result["confidence"].startswith("Low")
    assert "not enough" in result["confidence"]


def test_zero_shift_is_stable():
    onsets = [0.7, 1.5, 2.3, 3.1, 3.9, 4.7]
    result = estimate_offset(_wav(onsets), onsets)
    assert abs(result["offsetMs"]) <= 20


@pytest.mark.parametrize("shift_ms", [-180, -60, 60, 180])
def test_bidirectional_shifts(shift_ms: int):
    onsets = [0.6, 1.4, 2.2, 3.0, 3.8, 4.6]
    result = estimate_offset(_wav(onsets), [time - shift_ms / 1000 for time in onsets])
    assert abs(result["offsetMs"] - shift_ms) <= 20
