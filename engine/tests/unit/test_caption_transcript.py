import json
from pathlib import Path

from shorts_engine.api.context import build_context
from shorts_engine.common.paths import AppPaths


def test_caption_import_saves_and_reuses_transcript(tmp_path: Path):
    ctx = build_context(AppPaths(tmp_path / "engine"))
    project = ctx.projects.create("Captions")
    source = ctx.sources.create(
        project["id"],
        kind="url",
        url="https://www.youtube.com/watch?v=test",
        title="Caption source",
        duration_s=12.0,
        authorization_ack_at="2026-01-01T00:00:00Z",
    )
    caption = tmp_path / "sub.en.json3"
    caption.write_text(
        json.dumps(
            {
                "events": [
                    {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "Hello "}, {"utf8": "captions"}]},
                    {"tStartMs": 4000, "dDurationMs": 1500, "segs": [{"utf8": "Second"}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    first = __import__("asyncio").run(ctx.transcription.from_captions(source, [caption]))
    assert first is not None
    assert first["origin"] == "subtitle"
    assert first["segments"][0]["text"] == "Hello captions"
    assert first["segments"][0]["startS"] == 1.0
    assert first["wordTiming"] == "approximate"
    second = __import__("asyncio").run(ctx.transcription.from_captions(source, [caption]))
    assert second["id"] == first["id"]
    ctx.db.close()
