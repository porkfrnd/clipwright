from pathlib import Path

from shorts_engine.render.ass import ass_color, ass_time, build_ass, escape_filter_path
from shorts_engine.render.filters import (
    build_audio_chain,
    build_ffmpeg_command,
    build_video_chain,
    framing_filter,
    parse_progress_line,
)

STYLE = {
    "enabled": True,
    "font": "Bebas Neue",
    "fontSize": 64,
    "color": "#FFFFFF",
    "highlightColor": "#E8C77B",
    "outlineColor": "#0B0910",
    "outline": 4,
    "uppercase": True,
    "position": "lower_third",
    "maxLines": 2,
}


def segments():
    words = [
        {"startS": 1.0, "endS": 1.3, "text": "Find"},
        {"startS": 1.3, "endS": 1.7, "text": "the"},
        {"startS": 1.7, "endS": 2.2, "text": "moment."},
        {"startS": 2.5, "endS": 2.9, "text": "Then"},
        {"startS": 2.9, "endS": 3.4, "text": "make"},
        {"startS": 3.4, "endS": 3.9, "text": "it"},
        {"startS": 3.9, "endS": 4.3, "text": "travel."},
    ]
    return [{"startS": 1.0, "endS": 4.3, "text": " ".join(w["text"] for w in words), "words": words}]


def test_ass_header_and_geometry():
    content = build_ass(segments=segments(), start_s=1.0, end_s=4.3, style=STYLE)
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "Style: Clip,Bebas Neue,64" in content
    assert "MarginV, Encoding" in content


def test_ass_highlight_each_word_and_correct_offsets():
    content = build_ass(segments=segments(), start_s=1.0, end_s=4.3, style=STYLE)
    events = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 7
    assert "0:00:00.00,0:00:00.30" in events[0]
    assert r"{\c&H007BC7E8}FIND" in events[0]
    assert "{\\c&H00FFFFFF} THE" in events[0]
    # Highlight moves to the second word on the next event.
    assert "{\\c&H007BC7E8}THE" in events[1]


def test_ass_approximate_word_timing_is_phrase_level():
    content = build_ass(
        segments=segments(), start_s=1.0, end_s=4.3, style=STYLE, word_timing="approximate"
    )
    events = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(events) >= 1
    assert all("{\\c" in event for event in events)


def test_ass_time_and_color_helpers():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(3661.25) == "1:01:01.25"
    assert ass_color("#FFFFFF") == "&H00FFFFFF"
    assert ass_color("#000000", 0x66) == "&H66000000"


def test_filter_path_escapes_quotes_and_colons(tmp_path: Path):
    path = tmp_path / "a:b'c.ass"
    escaped = escape_filter_path(path)
    assert "\\:" in escaped
    assert "\\'" in escaped
    assert "\\" not in escaped.replace("\\:", "").replace("\\'", "")


def test_framing_layouts():
    fill = framing_filter({"layout": "fill"}, 30)
    assert "scale=1080:1920" in fill
    assert "crop=1080:1920" in fill
    blur = framing_filter({"layout": "blur"}, 30)
    assert "scale=540:960" in blur
    assert "gblur=sigma=19" in blur
    assert "scale=1080:1920" in blur
    assert "overlay=" in blur
    manual = framing_filter({"layout": "manual", "manual": {"x": 0.4, "y": 0.5, "w": 0.5, "h": 0.6}}, 30)
    assert "crop=iw*0.5000:ih*0.6000" in manual


def test_video_chain_skips_fps_for_native_30fps(tmp_path: Path):
    chain = build_video_chain(
        framing={"layout": "fill"},
        subtitles={"enabled": False},
        effects={"fade": False},
        duration=20.0,
        ass_path=None,
        fonts_dir=None,
        source_fps=30.0,
    )
    assert "fps=30" not in chain
    chain = build_video_chain(
        framing={"layout": "fill"},
        subtitles={"enabled": False},
        effects={"fade": False},
        duration=20.0,
        ass_path=None,
        fonts_dir=None,
        source_fps=60.0,
    )
    assert "fps=30" in chain


def test_video_chain_contains_ass_fps_and_effects(tmp_path: Path):
    chain = build_video_chain(
        framing={"layout": "fill"},
        subtitles={"enabled": True},
        effects={"fade": True, "progressBar": False, "cinematic": False},
        duration=20.0,
        ass_path=tmp_path / "clip.ass",
        fonts_dir=tmp_path,
    )
    assert "ass=filename=" in chain
    assert "fps=30" in chain
    assert "fade=t=in" in chain
    assert chain.endswith("format=yuv420p[vout]")


def test_audio_chain_without_and_with_music():
    chains, label = build_audio_chain(
        audio={"loudnessTarget": -14, "truePeak": -1.5}, measured=None, has_music=False, input_index=0, music_index=1, duration=20
    )
    assert label == "[aout]"
    assert "loudnorm=I=-14.0:TP=-1.5" in chains[0]
    assert "aresample=48000" in chains[0]

    measured = {
        "input_i": "-22.0",
        "input_tp": "-2.0",
        "input_lra": "6.0",
        "input_thresh": "-32.0",
        "target_offset": "0.1",
    }
    chains, label = build_audio_chain(
        audio={"loudnessTarget": -14, "truePeak": -1.5, "denoise": True, "voiceEnhance": True, "musicGainDb": -18},
        measured=measured,
        has_music=True,
        input_index=0,
        music_index=1,
        duration=20,
    )
    joined = "\n".join(chains)
    assert label == "[aout]"
    assert "afftdn" in joined
    assert "highpass" in joined
    assert "sidechaincompress" in joined
    assert "measured_I=-22.0" in joined


def test_ffmpeg_command_is_argument_array():
    command = build_ffmpeg_command(
        ffmpeg=["ffmpeg"],
        source=Path("/tmp/in.mp4"),
        start_s=10.0,
        duration=20.0,
        output=Path("/tmp/out.mp4"),
        encoder_args=["-c:v", "libx264", "-preset", "veryfast"],
        has_audio=True,
        music_path=None,
        framing={"layout": "fill"},
        subtitles={"enabled": False},
        effects={"fade": True},
        audio={"loudnessTarget": -14},
        ass_path=None,
        fonts_dir=None,
        measured=None,
        source_fps=30.0,
    )
    assert command[0] == "ffmpeg"
    assert "-filter_complex" in command
    assert "-ss" in command and "10.000" in command
    assert command[-1] == "/tmp/out.mp4"
    assert all(isinstance(part, str) for part in command)


def test_progress_parser():
    assert parse_progress_line("out_time_ms=12500000", 50.0) == 0.25
    assert parse_progress_line("out_time=00:00:12.500000", 50.0) == 0.25
    assert parse_progress_line("garbage", 50.0) is None
    assert parse_progress_line("out_time_ms=12500000", 0.0) is None


def _dialogue_seconds(value: str) -> float:
    h, m, s = value.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def _events(content: str):
    for line in content.splitlines():
        if line.startswith("Dialogue:"):
            fields = line.split(",", 9)
            yield _dialogue_seconds(fields[1]), _dialogue_seconds(fields[2]), fields[9]


def test_caption_lines_are_clipped_and_never_invent_text():
    from shorts_engine.render.ass import build_caption_lines

    source = [
        {
            "startS": 99.0,
            "endS": 106.0,
            "text": "before inside after",
            "words": [
                {"startS": 99.4, "endS": 100.2, "text": "before"},
                {"startS": 100.8, "endS": 102.0, "text": "inside"},
                {"startS": 108.0, "endS": 109.0, "text": "after"},
            ],
        }
    ]
    lines = build_caption_lines(source, start_s=100.5, end_s=102.0, max_lines=2)
    assert len(lines) == 1
    assert lines[0].text == "INSIDE"
    assert lines[0].start_s == 100.8
    assert lines[0].end_s == 102.0


def test_ass_events_use_clip_relative_time_for_a_late_source_range():
    source = [
        {
            "startS": 560.11,
            "endS": 580.08,
            "text": "First line here.",
            "words": [
                {"startS": 560.11, "endS": 561.0, "text": "First"},
                {"startS": 561.0, "endS": 561.8, "text": "line"},
                {"startS": 561.8, "endS": 562.5, "text": "here."},
            ],
        }
    ]
    content = build_ass(segments=source, start_s=560.11, end_s=580.08, style=STYLE)
    events = list(_events(content))
    assert events
    assert events[0][0] == 0.0
    assert all(0.0 <= start <= end <= 19.97 for start, end, _ in events)
    assert all(text.strip() for _, _, text in events)


def test_phrase_only_transcript_gets_one_caption_event():
    source = [{"startS": 2.0, "endS": 5.0, "text": "A phrase-only caption."}]
    content = build_ass(segments=source, start_s=2.0, end_s=5.0, style=STYLE, word_timing="approximate")
    events = list(_events(content))
    assert len(events) == 1
    assert "A PHRASE-ONLY CAPTION." in events[0][2]
    assert events[0][0] == 0.0
    assert events[0][1] == 3.0


def test_long_caption_wraps_into_explicit_rows():
    from shorts_engine.render.ass import MAX_CHARS_PER_LINE, build_caption_lines

    words = [
        {"startS": i * 0.25, "endS": i * 0.25 + 0.22, "text": f"WORD{i}"}
        for i in range(14)
    ]
    source = [{"startS": 0.0, "endS": 10.0, "text": "x", "words": words}]
    lines = build_caption_lines(source, start_s=0.0, end_s=10.0, max_lines=2)
    assert lines
    for line in lines:
        assert len(line.rows) <= 2
        for row in line.rows:
            assert sum(len(w.text) + (1 if i else 0) for i, w in enumerate(row)) <= MAX_CHARS_PER_LINE
    content = build_ass(segments=source, start_s=0.0, end_s=10.0, style=STYLE)
    exact = [line for line in content.splitlines() if line.startswith("Dialogue:") and "\\N" in line]
    assert exact
