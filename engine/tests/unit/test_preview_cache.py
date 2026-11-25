import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from shorts_engine.api.methods.projects import source_fetch_preview
from shorts_engine.api.params import FetchPreviewParams
from shorts_engine.common.paths import AppPaths
from shorts_engine.api.context import build_context


def test_concurrent_same_preview_downloads_once(tmp_path: Path):
    ctx = build_context(AppPaths(tmp_path / "engine"))
    project = ctx.projects.create("preview test")
    source = ctx.sources.create(
        project["id"],
        kind="url",
        url="https://example.test/video",
        title="Example",
        duration_s=120,
    )
    calls = 0

    async def fake_download(url, out_dir, *, start_s, end_s, max_height, cancel=None):
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        path = Path(out_dir) / "section.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-preview")
        return path

    ctx.ytdlp.download_section = fake_download
    app = SimpleNamespace(ctx=ctx)
    params = FetchPreviewParams(sourceId=source["id"], startS=30.0, endS=50.0)

    async def run():
        return await asyncio.gather(
            source_fetch_preview(app, params, {}),
            source_fetch_preview(app, params, {}),
        )

    first, second = asyncio.run(run())
    assert calls == 1
    assert {first["cached"], second["cached"]} == {False, True}
    assert first["path"] == second["path"]
    assert len(ctx.assets.for_source(source["id"], "preview")) == 1
    ctx.db.close()
