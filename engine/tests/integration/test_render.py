from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from shorts_engine.api.context import build_context
from shorts_engine.common.paths import AppPaths
from shorts_engine.render.service import RenderHooks, RenderOptions

REPO = Path(__file__).resolve().parents[3]
FIXTURE = REPO / "tests/fixtures/demo-lecture.mp4"


def seed_render_project(engine_dir: Path, count: int = 3):
    ctx = build_context(AppPaths(engine_dir))
    project = ctx.projects.create("Render test")
    source = ctx.sources.create(
        project["id"],
        kind="file",
        local_path=str(FIXTURE),
        title="Demo lecture",
        duration_s=48.0,
        width=1280,
        height=720,
        authorization_ack_at="2026-01-01T00:00:00Z",
    )
    segments = []
    sentences = [
        "Welcome to this test of the clip finding engine today we talk about small moments.",
        "The first lesson is simple. Start with a question that makes people curious.",
        "Then explain the answer in plain language. Do not hide the answer behind jargon.",
        "Finally close on a line people can repeat. That is what makes a clip travel.",
        "A small moment becomes a story when the ending gives the beginning a reason to exist.",
        "Keep the frame calm and let the words carry the weight of the moment.",
        "Test the ending before you publish it. If the last line is weak the clip will not travel.",
        "This last line exists so the synthetic fixture has enough speech for a three clip batch.",
    ]
    cursor = 0.7
    for index, sentence in enumerate(sentences):
        words = []
        tokens = sentence.split()
        word_cursor = cursor
        for token in tokens:
            words.append(
                {"seq": len(words), "start_s": round(word_cursor, 3), "end_s": round(word_cursor + 0.52, 3), "text": token}
            )
            word_cursor += 0.58
        end = round(min(47.2, word_cursor - 0.06), 3)
        if end <= cursor:
            break
        segments.append(
            {
                "seq": index,
                "seg_key": f"s{index:04d}",
                "start_s": round(cursor, 3),
                "end_s": end,
                "text": sentence,
                "words": words,
            }
        )
        cursor = end + 0.25
    transcript = ctx.transcripts.save(
        source["id"],
        origin="local_whisper",
        engine="local_whisper",
        model="tiny",
        language="en",
        params={},
        cache_key="render-test",
        word_timing="exact",
        segments=segments,
    )
    run = ctx.runs.create(source["id"], transcript["id"], "test-provider", "stub", {}, "test")
    ctx.runs.finish(run["id"], state="succeeded", token_usage={"totalTokens": 0})
    ranges = [(0.7, 16.5), (16.5, 32.5), (32.5, 47.4)][:count]
    ids = []
    for index, (start, end) in enumerate(ranges):
        cid = ctx.candidates.insert(
            source["id"],
            run["id"],
            {
                "category": "educational",
                "categories": ["educational"],
                "start_s": start,
                "end_s": end,
                "title": f"Moment {index + 1}",
                "excerpt": "Synthetic fixture speech for a render test.",
                "rationale": "A deterministic candidate used to test the renderer.",
                "ratings": {
                    "hook_strength": {"score": 4},
                    "context_completeness": {"score": 4},
                    "ending_quality": {"score": 4},
                    "standalone_clarity": {"score": 4},
                },
                "weaknesses": [],
                "fit_score": 80.0,
                "signals": {"durationFit": 1.0},
                "seg_start_key": f"s{min(index * 2, len(segments) - 1):04d}",
                "seg_end_key": f"s{min(index * 2 + 1, len(segments) - 1):04d}",
                "rank": index + 1,
            },
        )
        ids.append(cid)
    selections = ctx.selections.set(project["id"], ids, None)
    for selection in selections:
        ctx.edits.set(
            selection["id"],
            {
                "framing": {"layout": "fill", "zoom": 1.0},
                "subtitles": {
                    "enabled": True,
                    "fontSize": 64,
                    "position": "lower_third",
                    "uppercase": True,
                    "color": "#FFFFFF",
                    "highlightColor": "#E8C77B",
                },
                "effects": {"fade": True, "progressBar": False, "cinematic": False},
                "metadata": {"title": f"render-test-{selection['position']}"},
            },
        )
    return ctx, project, source, selections


def probe(path: Path) -> dict:
    output = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_name,width,height,r_frame_rate:format=duration",
            "-of", "json", str(path),
        ],
        text=True,
    )
    data = json.loads(output)
    video = next(s for s in data["streams"] if s["codec_name"] in ("h264", "hevc", "vp9"))
    return {"video": video, "format": data["format"], "streams": data["streams"]}


async def render(ctx, project, selections, output_dir: Path, cancel_after_first=False):
    events: list[dict] = []
    cancel = asyncio.Event()

    def item_done(item):
        events.append(item)
        if cancel_after_first and len(events) == 1:
            cancel.set()

    hooks = RenderHooks(
        progress=lambda *args: None,
        log=lambda *args: None,
        item_done=item_done,
        cancel=cancel,
    )
    result = await ctx.render.render_batch(
        project_id=project["id"],
        selection_ids=[s["id"] for s in selections],
        options=RenderOptions(output_dir=output_dir, quality="standard", prefer_hardware=False),
        hooks=hooks,
        job_tmp=output_dir / "tmp",
    )
    return result, events


@pytest.mark.slow
@pytest.mark.asyncio
async def test_render_three_clip_batch_and_validate_output(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLIPWRIGHT_RESOURCES", str(REPO / "resources"))
    ctx, project, source, selections = seed_render_project(tmp_path / "engine", count=3)
    output_dir = tmp_path / "outputs"
    result, events = await render(ctx, project, selections, output_dir)
    assert result["succeeded"] == 3
    assert result["failed"] == 0
    assert len(events) == 3
    for item in result["items"]:
        path = Path(item["outputPath"])
        assert path.exists()
        info = probe(path)
        assert info["video"]["codec_name"] == "h264"
        assert info["video"]["width"] == 1080
        assert info["video"]["height"] == 1920
        assert float(info["format"]["duration"]) > 10
        assert any(s["codec_name"] == "aac" for s in info["streams"])
        # Full decode pass catches corrupt frames that ffprobe metadata cannot.
        subprocess.run(
            ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"],
            check=True,
            timeout=180,
        )
    # Subtitle pixels are in the lower third (the ASS style uses 1080x1920 coordinates).
    first = Path(result["items"][0]["outputPath"])
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", "5", "-i", str(first), "-frames:v", "1", "-y", str(frame)],
        check=True,
        timeout=60,
    )
    from PIL import Image

    image = Image.open(frame).convert("RGB")
    width, height = image.size
    lower = image.crop((0, int(height * 0.62), width, height))
    pixels = list(lower.getdata())
    gold = sum(1 for r, g, b in pixels if r > 170 and g > 140 and b < 150)
    white = sum(1 for r, g, b in pixels if r > 220 and g > 220 and b > 220)
    assert gold + white > 200, "expected subtitle glyph pixels in the lower third"
    ctx.db.close()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_cancel_mid_batch_leaves_no_partial_outputs(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CLIPWRIGHT_RESOURCES", str(REPO / "resources"))
    ctx, project, source, selections = seed_render_project(tmp_path / "engine", count=3)
    output_dir = tmp_path / "outputs"
    with pytest.raises(Exception) as info:
        await render(ctx, project, selections, output_dir, cancel_after_first=True)
    assert getattr(info.value, "code", "") in ("JOB_CANCELLED", "CANCELLED")
    outputs = [p for p in output_dir.glob("*.mp4") if p.is_file()]
    parts = list(output_dir.glob("*.part"))
    # One completed clip is allowed; nothing partial may remain.
    assert len(outputs) == 1
    assert parts == []
    ctx.db.close()
