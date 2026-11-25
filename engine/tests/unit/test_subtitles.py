import json
from pathlib import Path

from shorts_engine.transcription.subtitles import (
    parse_json3,
    parse_subtitle_file,
    parse_verbose_json,
    parse_vtt,
)


def test_vtt_inline_timestamps_and_cleanup(tmp_path: Path):
    text = """WEBVTT

00:00:01.000 --> 00:00:04.000
<00:00:01.000><c>Hello</c><00:00:01.900> there<00:00:02.800> friend</c>

00:00:05.000 --> 00:00:07.500
Second <i>line</i> &amp; more
"""
    parsed = parse_vtt(text)
    assert parsed.word_timing == "exact"
    assert parsed.origin == "subtitle"
    assert [s.text for s in parsed.segments] == ["Hello there friend", "Second line & more"]
    assert parsed.segments[0].words[0].start_s == 1.0
    assert parsed.segments[0].words[-1].text == "friend"
    assert all(w.start_s >= 1.0 for w in parsed.segments[0].words)
    path = tmp_path / "captions.en.vtt"
    path.write_text(text, encoding="utf-8")
    assert len(parse_subtitle_file(path).segments) == 2


def test_vtt_deduplicates_rolling_captions():
    text = """WEBVTT

00:00:01.000 --> 00:00:03.000
one two three

00:00:01.000 --> 00:00:03.000
one two three

00:00:03.000 --> 00:00:05.000
four five
"""
    parsed = parse_vtt(text)
    assert [s.text for s in parsed.segments] == ["one two three", "four five"]
    # Phrase-level timing is distributed and monotonic.
    starts = [w.start_s for s in parsed.segments for w in s.words]
    ends = [w.end_s for s in parsed.segments for w in s.words]
    assert starts == sorted(starts)
    assert all(e >= s for s, e in zip(starts, ends))
    assert parsed.word_timing == "approximate"


def test_json3_event_grouping():
    data = {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 2200, "segs": [{"utf8": "Hello "}, {"utf8": "world"}]},
            {"tStartMs": 3200, "dDurationMs": 1800, "segs": [{"utf8": "Again"}]},
            {"tStartMs": 5000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
        ]
    }
    parsed = parse_json3(data)
    assert [s.text for s in parsed.segments] == ["Hello world", "Again"]
    assert parsed.segments[0].start_s == 1.0
    assert abs(parsed.segments[0].end_s - 3.2) < 0.001
    assert parsed.word_timing == "approximate"


def test_verbose_json_prefers_exact_word_timings():
    data = {
        "language": "en",
        "duration": 4.0,
        "segments": [
            {
                "start": 0.5,
                "end": 2.5,
                "text": " words here",
                "words": [
                    {"word": "words", "start": 0.5, "end": 1.2, "probability": 0.9},
                    {"word": "here", "start": 1.3, "end": 2.4, "probability": 0.8},
                ],
            }
        ],
    }
    parsed = parse_verbose_json(data)
    assert parsed.word_timing == "exact"
    assert parsed.language == "en"
    assert parsed.engine == "openai-compatible"
    assert parsed.segments[0].words[1].end_s == 2.4


def test_verbose_json_without_words_is_approximate():
    data = {"segments": [{"start": 0.0, "end": 2.0, "text": "no timing"}]}
    parsed = parse_verbose_json(data)
    assert parsed.word_timing == "approximate"
    assert parsed.segments[0].words


def test_subtitle_json_file(tmp_path: Path):
    path = tmp_path / "captions.json3"
    path.write_text(json.dumps({"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "hi"}]}]}))
    parsed = parse_subtitle_file(path)
    assert parsed.segments[0].text == "hi"
