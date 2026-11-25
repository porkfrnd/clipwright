from shorts_engine.discovery.boundaries import refine_boundaries

WORDS = [
    "This", "is", "the", "first", "sentence.", "Then", "a", "second", "thought",
    "that", "keeps", "going", "for", "a", "while.", "Finally", "a", "third", "line",
    "that", "closes", "the", "idea.",
]


def make_segments(sentence_lengths=(5, 10, 8), start=0.5, gap=0.4):
    segments = []
    cursor = start
    word_cursor = 0
    for length in sentence_lengths:
        words = []
        seg_start = cursor
        for _ in range(length):
            text = WORDS[word_cursor % len(WORDS)]
            word_cursor += 1
            words.append({"startS": round(cursor, 2), "endS": round(cursor + 0.42, 2), "text": text})
            cursor += 0.5
        segments.append(
            {
                "segKey": f"s{len(segments):04d}",
                "startS": round(seg_start, 2),
                "endS": round(cursor - 0.08, 2),
                "text": " ".join(w["text"] for w in words),
                "words": words,
            }
        )
        cursor += gap
    return segments


def test_boundaries_snap_to_spoken_words_and_finish_sentence():
    segments = make_segments()
    # Start in the middle of the word "first" and end inside "while."
    result = refine_boundaries(start_s=1.05, end_s=8.1, segments=segments, min_duration=5, source_end=20.0)
    assert result is not None
    assert result.start_s <= 1.05
    assert result.end_s >= 8.1
    assert result.signals["wordCount"] > 0
    assert result.signals["sentenceAlignedStart"] is True
    # Pads must not create a clip outside the source.
    assert 0 <= result.start_s
    assert result.end_s <= 20.0


def test_boundaries_extend_short_clip_to_minimum_duration():
    segments = make_segments()
    result = refine_boundaries(start_s=0.5, end_s=2.0, segments=segments, min_duration=5, source_end=20.0)
    assert result is not None
    assert result.duration >= 5.0


def test_boundaries_reject_when_source_is_shorter_than_minimum():
    segments = make_segments(sentence_lengths=(3,), start=0.0)
    assert refine_boundaries(start_s=0.0, end_s=1.5, segments=segments, min_duration=15.0) is None


def test_boundaries_respect_maximum_duration():
    segments = make_segments(sentence_lengths=(30, 30, 30), gap=0.2)
    result = refine_boundaries(
        start_s=0.5, end_s=40.0, segments=segments, min_duration=15, max_duration=30, source_end=80.0
    )
    assert result is not None
    assert result.duration <= 30.0 + 0.001


def test_boundaries_clamp_to_source_end():
    segments = make_segments()
    source_end = segments[-1]["endS"]
    result = refine_boundaries(start_s=0.0, end_s=999, segments=segments, min_duration=5, source_end=source_end)
    assert result is not None
    assert result.end_s <= source_end


def test_boundaries_require_segments():
    assert refine_boundaries(start_s=0, end_s=20, segments=[]) is None


def test_batch_windows_deduplicates_overlap_and_keeps_ranges():
    from shorts_engine.discovery.chunker import batch_windows, build_windows

    segments = []
    for i in range(10):
        segments.append(
            {
                "seq": i,
                "segKey": f"s{i:04d}",
                "startS": float(i * 60),
                "endS": float(i * 60 + 55),
                "text": f"Segment {i}",
            }
        )
    windows = build_windows(segments, target_s=180, overlap=0.22)
    batches = batch_windows(windows, size=2)
    assert len(batches) == (len(windows) + 1) // 2
    assert batches[0].source_windows == [w.index for w in windows[:2]]
    keys = [s["segKey"] for s in batches[0].segments]
    assert keys == list(dict.fromkeys(keys)), "overlapping segment must appear once"
    assert batches[0].start_s == windows[0].start_s
    assert batches[0].end_s == windows[1].end_s
