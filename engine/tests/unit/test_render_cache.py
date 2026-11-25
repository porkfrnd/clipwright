import asyncio
from pathlib import Path

import pytest

from shorts_engine.api.context import build_context
from shorts_engine.common.paths import AppPaths
from shorts_engine.render.service import RenderHooks


class FakeYtDlp:
    def __init__(self) -> None:
        self.calls = 0

    async def download_section(self, url, out_dir, *, start_s, end_s, max_height=1080, cancel=None):
        self.calls += 1
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / "section.mp4"
        target.write_bytes(b"fake section")
        return target


@pytest.mark.asyncio
async def test_render_section_cache_is_reused_and_boundary_invalidated(tmp_path: Path):
    ctx = build_context(AppPaths(tmp_path / "engine"))
    project = ctx.projects.create("Cache test")
    source = ctx.sources.create(
        project["id"],
        kind="url",
        url="https://example.test/video",
        duration_s=120.0,
        title="URL source",
        authorization_ack_at="2026-01-01T00:00:00Z",
    )
    fake = FakeYtDlp()
    ctx.render.ytdlp = fake  # type: ignore[assignment]
    candidate = {"id": "candidate-1", "startS": 20.0, "endS": 40.0}
    hooks = RenderHooks()
    job_tmp = ctx.paths.job_tmp("cache-test")

    first, first_offset, first_note = await ctx.render._prepare_media(
        source=source, candidate=candidate, job_tmp=job_tmp, hooks=hooks,
        start=20.0, end=40.0, index=1, total=1, selection_id="selection-1",
    )
    second, second_offset, second_note = await ctx.render._prepare_media(
        source=source, candidate=candidate, job_tmp=job_tmp, hooks=hooks,
        start=20.0, end=40.0, index=1, total=1, selection_id="selection-1",
    )
    assert fake.calls == 1
    assert first == second
    assert first_offset == second_offset == 17.0
    assert str(first).startswith(str(ctx.paths.assets))
    assert "Reused" in second_note

    # Editing the boundaries must not reuse a section downloaded for the old range.
    third, third_offset, _ = await ctx.render._prepare_media(
        source=source, candidate=candidate, job_tmp=job_tmp, hooks=hooks,
        start=20.0, end=50.0, index=1, total=1, selection_id="selection-1",
    )
    assert fake.calls == 2
    assert third_offset == 17.0
    assert third != first
    ctx.db.close()
