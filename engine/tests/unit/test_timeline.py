from __future__ import annotations

import pytest

from shorts_engine.render.timeline import map_time, plan_timeline, remap_segments


def transcript(words):
    return [{"startS": words[0][0], "endS": words[-1][1], "text": " ".join(w[2] for w in words), "words": [
        {"startS": a, "endS": b, "text": t} for a, b, t in words
    ]}]


def test_pause_plan_keeps_breath_and_never_touches_words():
    segments = transcript([(1.0, 1.4, "First"), (2.4, 2.8, "Second"), (3.2, 3.6, "Third")])
    plan = plan_timeline(segments, start_s=1.0, end_s=4.0, pause_threshold_s=0.6, min_pause_s=0.25)
    assert plan["supported"] is True
    assert len(plan["pauses"]) == 1
    pause = plan["pauses"][0]
    # The 1.0 s gap leaves 0.12 s padding on either side.
    assert pause["startS"] > 1.4 and pause["endS"] < 2.4
    assert plan["removedS"] > 0.5
    assert plan["plannedDurationS"] < 3.0
    assert all(cut["startS"] >= 1.4 or cut["endS"] <= 2.4 for cut in plan["cuts"])


def test_map_time_collapses_cut_and_preserves_later_timing():
    segments = transcript([(1.0, 1.4, "A"), (2.4, 2.8, "B")])
    plan = plan_timeline(segments, start_s=1.0, end_s=3.0)
    cuts = plan["cuts"]
    assert map_time(1.0, start_s=1.0, cuts=cuts) == 0.0
    assert map_time(1.4, start_s=1.0, cuts=cuts) == pytest.approx(0.4)
    assert map_time(2.0, start_s=1.0, cuts=cuts) == pytest.approx(0.52)
    assert map_time(2.8, start_s=1.0, cuts=cuts) == pytest.approx(1.04)
    assert plan["plannedDurationS"] == pytest.approx(1.24)


def test_remapped_subtitles_follow_shortened_audio():
    segments = transcript([(1.0, 1.4, "A"), (2.4, 2.8, "B")])
    plan = plan_timeline(segments, start_s=1.0, end_s=3.0)
    mapped = remap_segments(segments, start_s=1.0, end_s=3.0, cuts=plan["cuts"])
    words = [word for segment in mapped for word in segment["words"]]
    assert words[0]["startS"] == 0.0
    assert words[1]["startS"] == pytest.approx(0.64)
    assert mapped[-1]["endS"] == pytest.approx(1.04)


def test_fillers_are_opt_in_and_removed_from_subtitles_only_when_requested():
    segments = transcript([(1.0, 1.2, "So"), (1.2, 1.45, "um"), (1.6, 2.0, "yes")])
    baseline = plan_timeline(segments, start_s=1.0, end_s=2.0, remove_fillers=False)
    assert baseline["fillers"] == []
    plan = plan_timeline(segments, start_s=1.0, end_s=2.0, remove_fillers=True)
    assert [filler["text"] for filler in plan["fillers"]] == ["um"]
    mapped = remap_segments(segments, start_s=1.0, end_s=2.0, cuts=plan["cuts"])
    text = " ".join(word["text"] for segment in mapped for word in segment["words"])
    assert "um" not in text.lower()
    assert "yes" in text.lower()


def test_phrase_level_transcript_refuses_to_tighten():
    plan = plan_timeline(
        transcript([(1.0, 1.4, "hello"), (2.4, 2.8, "world")]),
        start_s=1.0,
        end_s=3.0,
        word_timing="approximate",
    )
    assert plan["supported"] is False
    assert "phrase-level" in plan["reason"]
    assert plan["cuts"] == []
