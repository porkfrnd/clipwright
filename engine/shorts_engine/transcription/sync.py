from __future__ import annotations

import io
import math
import wave
from typing import Any

import numpy as np

FRAME_MS = 10
MAX_OFFSET_MS = 500


def _pcm_from_wav(raw: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(raw), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("expected 16-bit PCM")
    data = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, rate


def _envelope(samples: np.ndarray, rate: int, frame_ms: int = FRAME_MS) -> np.ndarray:
    size = max(1, int(rate * frame_ms / 1000))
    usable = (len(samples) // size) * size
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[:usable].reshape(-1, size)
    return np.sqrt(np.mean(np.square(frames), axis=1))


def estimate_offset(
    wav_bytes: bytes,
    word_times_s: list[float],
    *,
    max_offset_ms: int = MAX_OFFSET_MS,
) -> dict[str, Any]:
    """Estimate a global subtitle shift from audio energy onsets.

    Positive output means the subtitles should move later. This is deliberately
    conservative: it reports low confidence instead of inventing an offset when
    there are too few words or no clear peak.
    """
    samples, rate = _pcm_from_wav(wav_bytes)
    env = _envelope(samples, rate)
    frame_s = FRAME_MS / 1000.0
    if env.size == 0 or not word_times_s:
        return {
            "offsetMs": 0,
            "confidence": "Low: not enough speech",
            "wordsUsed": 0,
            "separation": 0.0,
        }
    onsets = [t for t in word_times_s if 0.15 <= t <= env.size * frame_s - 0.15]
    if len(onsets) < 3:
        return {
            "offsetMs": 0,
            "confidence": "Low: not enough speech",
            "wordsUsed": len(onsets),
            "separation": 0.0,
        }
    # An onset is a quiet lookback followed by a loud lookahead. Scoring the
    # contrast (rather than the derivative peak) lands on the first frame of
    # speech and stays stable as the burst gets louder.
    lookback = np.maximum(env, 0.0)
    smooth = np.sqrt(np.convolve(lookback, np.ones(3, dtype=np.float32) / 3.0, mode="same"))
    mean = float(np.mean(smooth))
    std = float(np.std(smooth)) or 1.0
    candidates: list[tuple[int, float]] = []
    step = 5
    for offset_ms in range(-max_offset_ms, max_offset_ms + 1, step):
        score = 0.0
        used = 0
        for onset in onsets:
            index = int(round((onset + offset_ms / 1000.0) / frame_s))
            if 4 <= index < smooth.size - 6:
                before = float(np.max(smooth[index - 4:index]))
                after = float(np.max(smooth[index:index + 6]))
                score += max(0.0, after - before)
                used += 1
        if used:
            candidates.append((offset_ms, score / used))
    if not candidates:
        return {"offsetMs": 0, "confidence": "Low: not enough speech", "wordsUsed": 0, "separation": 0.0}
    values = np.array([value for _, value in candidates])
    order = np.argsort(values)
    best_index = int(order[-1])
    best_offset, best_score = candidates[best_index]
    median = float(np.median(values)) or 1e-9
    separation = (best_score - median) / std
    # Prefer the earliest frame of a plateau; otherwise a broad energy hump can
    # pull the estimate a few frames late.
    plateau = [candidates[i][0] for i in order[::-1] if candidates[i][1] >= best_score * 0.985]
    if plateau:
        best_offset = min(plateau)
    high = len(onsets) >= 4 and separation >= 0.55
    return {
        "offsetMs": int(best_offset),
        "confidence": "High" if high else "Low: not enough clear speech",
        "wordsUsed": len(onsets),
        "separation": round(float(separation), 3),
        "maxOffsetMs": max_offset_ms,
    }


def energy_peaks(wav_bytes: bytes, *, threshold: float = 0.35) -> list[float]:
    """Test helper: return frame times with a clear energy rise."""
    samples, rate = _pcm_from_wav(wav_bytes)
    env = _envelope(samples, rate)
    if env.size == 0:
        return []
    peak = float(np.max(env)) or 1.0
    return [round(i * FRAME_MS / 1000.0, 3) for i, value in enumerate(env) if value >= peak * threshold]
