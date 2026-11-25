from pathlib import Path

import pytest

from shorts_engine.common.proc import CommandResult
from shorts_engine.ingest.binaries import BinaryPaths
from shorts_engine.ingest.ytdlp import YtDlp


class FakeRunner:
    def __init__(self, out_dir: Path, failures: int) -> None:
        self.out_dir = out_dir
        self.failures = failures
        self.calls: list[list[str]] = []

    async def run(self, args, **_kwargs):
        self.calls.append(args)
        if len(self.calls) <= self.failures:
            return CommandResult(args, 1, "", "ERROR: [youtube] x: HTTP Error 403: Forbidden")
        (self.out_dir / "section.mp4").write_bytes(b"fake video")
        return CommandResult(args, 0, "", "")


def bins() -> BinaryPaths:
    return BinaryPaths(
        ffmpeg="/usr/bin/ffmpeg",
        ffprobe="/usr/bin/ffprobe",
        ytdlp="/usr/bin/yt-dlp",
        ytdlp_kind="binary",
        js_runtime=None,
        js_runtime_kind=None,
        ffmpeg_origin="/usr/bin",
        ytdlp_origin="/usr/bin",
        ffmpeg_network=None,
    )


@pytest.mark.asyncio
async def test_youtube_section_retries_with_alternate_client(tmp_path: Path):
    runner = FakeRunner(tmp_path, failures=1)
    ytdlp = YtDlp(bins(), runner)  # type: ignore[arg-type]
    result = await ytdlp.download_section(
        "https://www.youtube.com/watch?v=abc123", tmp_path, start_s=10, end_s=20
    )
    assert result == tmp_path / "section.mp4"
    assert len(runner.calls) == 2
    assert "--extractor-args" in runner.calls[1]
    assert "youtube:player_client=web_embedded" in runner.calls[1]
    assert "--retries" in runner.calls[0]


@pytest.mark.asyncio
async def test_non_youtube_section_retries_progressive_before_fallback(tmp_path: Path):
    runner = FakeRunner(tmp_path, failures=1)
    ytdlp = YtDlp(bins(), runner)  # type: ignore[arg-type]
    await ytdlp.download_section("https://vimeo.com/123", tmp_path, start_s=1, end_s=2)
    assert len(runner.calls) == 2
    assert "--extractor-args" not in runner.calls[1]


def test_cookies_file_is_passed_to_downloader(tmp_path: Path):
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    ytdlp = YtDlp(bins(), FakeRunner(tmp_path, failures=0))  # type: ignore[arg-type]
    ytdlp.cookies_file = str(cookie_file)
    args = ytdlp._base_args()
    assert "--cookies" in args
    assert args[args.index("--cookies") + 1] == str(cookie_file)


class MetadataRunner(FakeRunner):
    async def run(self, args, **_kwargs):
        self.calls.append(args)
        if len(self.calls) == 1:
            return CommandResult(args, 1, "", "ERROR: [youtube] x: HTTP Error 403: Forbidden")
        return CommandResult(
            args,
            0,
            '{"title":"Retry worked","duration":42,"webpage_url":"https://www.youtube.com/watch?v=abc123"}\n',
            "",
        )


@pytest.mark.asyncio
async def test_youtube_metadata_retries_with_alternate_client(tmp_path: Path):
    runner = MetadataRunner(tmp_path, failures=0)
    ytdlp = YtDlp(bins(), runner)  # type: ignore[arg-type]
    info = await ytdlp.metadata("https://www.youtube.com/watch?v=abc123")
    assert info["title"] == "Retry worked"
    assert len(runner.calls) == 2
    assert "youtube:player_client=web_embedded" in runner.calls[1]


class PartialSubtitleRunner(FakeRunner):
    async def run(self, args, **_kwargs):
        self.calls.append(args)
        (self.out_dir / "sub.en-orig.json3").write_text('{"events":[]}', encoding="utf-8")
        return CommandResult(args, 1, "", "ERROR: Unable to download video subtitles for 'en': HTTP Error 429")


@pytest.mark.asyncio
async def test_subtitles_keep_successful_language_when_another_hits_429(tmp_path: Path):
    runner = PartialSubtitleRunner(tmp_path, failures=0)
    ytdlp = YtDlp(bins(), runner)  # type: ignore[arg-type]
    files = await ytdlp.download_subtitles("https://www.youtube.com/watch?v=abc123", tmp_path)
    assert [p.name for p in files] == ["sub.en-orig.json3"]
    assert len(runner.calls) == 1
