from shorts_engine.discovery.dedupe import dedupe_candidates, iou, text_similarity
from shorts_engine.discovery.score import clip_fit, fit_explanation


def cand(start, end, fit, title, cats=("insight",), excerpt="same words"):
    return {
        "start_s": start,
        "end_s": end,
        "fit_score": fit,
        "title": title,
        "excerpt": excerpt,
        "categories": list(cats),
    }


def test_iou_overlap_math():
    assert iou(0, 10, 5, 15) == 0.3333333333333333
    assert iou(0, 10, 10, 20) == 0.0
    assert iou(0, 10, 0, 10) == 1.0
    assert iou(3, 3, 3, 3) == 0.0


def test_text_similarity_bounds():
    assert text_similarity("Same", "same") == 1.0
    assert text_similarity("", "") == 1.0
    assert text_similarity("abc", "xyz") < 0.5


def test_dedupe_keeps_strongest_and_unions_categories():
    kept = dedupe_candidates(
        [
            cand(0, 30, 70, "Lower", ("insight",)),
            cand(1, 31, 91, "Higher", ("educational",)),
            cand(60, 90, 80, "Distinct", ("storytelling",), excerpt="entirely different text"),
        ]
    )
    assert [c["title"] for c in kept] == ["Higher", "Distinct"]
    assert set(kept[0]["categories"]) == {"insight", "educational"}


def test_dedupe_merges_similar_titles_even_without_overlap():
    kept = dedupe_candidates(
        [
            cand(0, 20, 80, "The exact same title", ("insight",)),
            cand(40, 60, 70, "The exact same title", ("educational",)),
        ],
        iou_threshold=0.99,
    )
    assert len(kept) == 1
    assert set(kept[0]["categories"]) == {"insight", "educational"}


def test_clip_fit_is_bounded_and_monotonic():
    ratings = {
        "hook_strength": {"score": 5},
        "context_completeness": {"score": 5},
        "ending_quality": {"score": 5},
        "standalone_clarity": {"score": 5},
    }
    signals = {
        "sentenceAlignedStart": True,
        "sentenceAlignedEnd": True,
        "durationFit": 1.0,
        "speechContinuity": 1.0,
    }
    best = clip_fit(ratings, signals)
    worst = clip_fit(
        {k: {"score": 1} for k in ratings},
        {"sentenceAlignedStart": False, "sentenceAlignedEnd": False, "durationFit": 0, "speechContinuity": 0},
    )
    assert best == 100.0
    assert worst == 0.0
    assert best > clip_fit({k: {"score": 3} for k in ratings}, signals) > worst


def test_clip_fit_defaults_missing_ratings_and_clamps_out_of_range():
    signals = {
        "sentenceAlignedStart": True,
        "sentenceAlignedEnd": False,
        "durationFit": 0.8,
        "speechContinuity": 0.7,
    }
    assert 0 <= clip_fit({}, signals) <= 100
    assert clip_fit({"hook_strength": {"score": 99}}, signals) <= 100
    assert "not a prediction" in fit_explanation()
