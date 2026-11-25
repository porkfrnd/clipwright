from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from shorts_engine.common.resources import fonts_dir
from shorts_engine.render.ass import build_ass, write_ass
from shorts_engine.render.filters import build_ffmpeg_command

ROOT = Path(__file__).resolve().parents[3]
FPS = 30


def _media(tmp_path: Path, duration: float = 4.0) -> tuple[Path, Path]:
    """A dark frame with a tone burst at 0.5 s and 2.5 s, no burned text."""
    rate = 16000
    samples = np.zeros(int(duration * rate), dtype=np.float32)
    for onset in (0.5, 2.5):
        start = int(onset * rate)
        length = int(0.24 * rate)
        t = np.arange(length) / rate
        tone = np.sin(2 * np.pi * 660 * t) * np.hanning(length) * 0.5
        samples[start : start + length] += tone.astype(np.float32)
    pcm = np.clip(samples * 32767, -32768, 32767).astype("<i2")
    wav = tmp_path / "voice.wav"
    with wave.open(str(wav), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    video = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x101014:s=640x360:r={FPS}:d={duration}",
            "-i", str(wav), "-shortest",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            str(video),
        ],
        check=True,
    )
    return video, wav


def _gold_frames(clip: Path, out_dir: Path) -> list[float]:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(clip), "-vf", f"fps={FPS}", str(out_dir / "%04d.png")],
        check=True,
    )
    hits: list[float] = []
    for index, path in enumerate(sorted(out_dir.glob("*.png"))):
        image = np.asarray(Image.open(path).convert("RGB"))
        # Subtitle fill is warm white/gold on a dark frame. Count a generous
        # threshold to avoid encoder noise; one glyph gives thousands of px.
        mask = (image[:, :, 0] > 170) & (image[:, :, 1] > 140) & (image[:, :, 2] > 90)
        if int(mask.sum()) > 120:
            hits.append(index / FPS)
    return hits


@pytest.mark.parametrize("source_start", [0.0, 2.0])
def test_burned_subtitle_lands_on_spoken_word(tmp_path: Path, source_start: float):
    duration = 3.0
    video, _wav = _media(tmp_path, duration + source_start)
    word_source = source_start + 0.5
    segments = [
        {
            "startS": word_source,
            "endS": word_source + 0.24,
            "text": "ALPHA",
            "words": [{"startS": word_source, "endS": word_source + 0.24, "text": "ALPHA"}],
        }
    ]
    style = {
        "enabled": True,
        "font": "Bebas Neue",
        "fontSize": 140,
        "color": "#FFFFFF",
        "highlightColor": "#E8C77B",
        "outlineColor": "#000000",
        "outline": 4,
        "background": False,
        "position": "center",
        "maxLines": 1,
        "uppercase": True,
    }
    ass = write_ass(
        tmp_path / "captions.ass",
        build_ass(
            segments=segments,
            start_s=source_start,
            end_s=source_start + 1.5,
            style=style,
            word_timing="exact",
        ),
    )
    output = tmp_path / "rendered.mp4"
    cmd = build_ffmpeg_command(
        ffmpeg=["ffmpeg"],
        source=video,
        start_s=source_start,
        duration=1.5,
        output=output,
        encoder_args=["-c:v", "libx264", "-preset", "veryfast", "-crf", "24"],
        has_audio=True,
        music_path=None,
        framing={"layout": "fill"},
        subtitles=style,
        effects={"fade": False},
        audio={},
        ass_path=ass,
        fonts_dir=fonts_dir(),
        measured={},
        source_fps=FPS,
    )
    subprocess.run(cmd, check=True)
    hits = _gold_frames(output, tmp_path / "frames")
    assert hits, "no subtitle pixels were found in the rendered clip"
    first = min(hits)
    expected = 0.5
    # A caption event begins on the first frame at or after its timestamp. At
    # 30 fps one frame is 33.3 ms; allow exactly that quantisation, no drift.
    assert first - expected <= (1 / FPS) + 0.001, (first, expected)
    assert expected - first <= (1 / FPS) + 0.001, (first, expected)
