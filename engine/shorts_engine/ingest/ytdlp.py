from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..common.errors import CancelledError, EngineError
from ..common.proc import ProcessRunner
from .binaries import BinaryPaths, ffmpeg_command, ytdlp_command
from .validate import validate_source_url


def _is_youtube(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com"


def _progressive_format(max_height: int) -> str:
    # A single progressive stream avoids DASH range requests, which are the
    # first thing YouTube's bot/rate limiting tends to reject.
    return f"b[height<={max_height}][vcodec^=avc1]/b[height<={max_height}]/b"


def _video_format(max_height: int) -> str:
    """Prefer H.264 so Chromium's preview and the bundled decoder agree.

    AV1 is accepted only as a last resort; YouTube sometimes serves AV1-only
    360p DASH streams, and the browser preview is more predictable with H.264.
    """
    return (
        f"bv*[height<={max_height}][vcodec^=avc1]+ba/"
        f"b[height<={max_height}][vcodec^=avc1]/"
        f"b[height<={max_height}]/b"
    )


def map_ytdlp_error(stderr: str, *, code_hint: str | None = None) -> EngineError:
    text = stderr or ""
    low = text.lower()
    if "sign in to confirm" in low or "not a bot" in low or "cookies" in low and "required" in low:
        return EngineError(
            "SOURCE_DOWNLOAD_BLOCKED",
            "This site is asking the downloader to sign in. Add a YouTube cookies.txt under "
            "Settings → Downloads, update the downloader, or import the video file from disk.",
            details={"hint": "SITE_SIGNIN"},
            retryable=True,
        )
    if "private video" in low or "members-only" in low or "login required" in low:
        return EngineError(
            "SOURCE_PRIVATE",
            "This video is private or members-only. Import a local copy if you are authorized to use it.",
        )
    if "http error 403" in low or "forbidden" in low or "po token" in low:
        return EngineError(
            "SOURCE_DOWNLOAD_BLOCKED",
            "The site refused the download (403). Clipwright already retries and reuses cached "
            "previews; if it persists, add cookies under Settings → Downloads, update the "
            "downloader, or import the file from disk.",
            details={"hint": "TOKEN_OR_403"},
            retryable=True,
        )
    if "unsupported url" in low:
        return EngineError("SOURCE_UNSUPPORTED", "The downloader does not support this link. Import the file from disk instead.")
    if "video unavailable" in low or "removed by the uploader" in low:
        return EngineError("SOURCE_UNAVAILABLE", "That video is unavailable on the site.")
    if any(k in low for k in ("timed out", "temporary failure", "connection", "network is unreachable", "ssl")):
        return EngineError(
            "SOURCE_NETWORK", "The site could not be reached. Check your connection and try again.", retryable=True
        )
    if "ffmpeg" in low and "not found" in low:
        return EngineError("FFMPEG_MISSING", "FFmpeg is needed to finish this download but was not found.")
    return EngineError(
        code_hint or "SOURCE_DOWNLOAD_FAILED",
        "The download did not finish. You can try again, update the downloader, or import the file from disk.",
        details={"downloadOutput": text[-1200:]} if text else {},
        retryable=True,
    )


def summarize_metadata(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("_type") == "playlist" and data.get("entries"):
        # Single-video import policy: use the first entry but expose the count so the UI can explain.
        first = next((e for e in data["entries"] if e), None)
        if first:
            data = first
    thumbs = sorted(
        [t for t in (data.get("thumbnails") or []) if t.get("url")],
        key=lambda t: (t.get("width") or 0) * (t.get("height") or 0),
        reverse=True,
    )
    subtitles = data.get("subtitles") or {}
    automatic = data.get("automatic_captions") or {}
    caption_langs = sorted(set(subtitles.keys()) | set(automatic.keys()))
    manual_langs = sorted(subtitles.keys())
    return {
        "title": data.get("title") or "Untitled video",
        "channel": data.get("uploader") or data.get("channel"),
        "duration_s": float(data["duration"]) if data.get("duration") else None,
        "width": data.get("width"),
        "height": data.get("height"),
        "fps": data.get("fps"),
        "language": data.get("language"),
        "thumbnail": thumbs[0]["url"] if thumbs else data.get("thumbnail"),
        "webpage_url": data.get("webpage_url"),
        "extractor": data.get("extractor_key") or data.get("extractor"),
        "caption_languages": caption_langs,
        "manual_caption_languages": manual_langs,
        "automatic_caption_languages": sorted(automatic.keys()),
        "live_status": data.get("live_status"),
        "view_count": data.get("view_count"),
        "upload_date": data.get("upload_date"),
        "description": (data.get("description") or "")[:2000],
    }


class YtDlp:
    def __init__(self, bins: BinaryPaths, runner: ProcessRunner) -> None:
        self.bins = bins
        self.runner = runner
        # Optional Netscape-format cookies.txt for videos that require a
        # signed-in session. Configured in Settings; never sent to an AI provider.
        self.cookies_file: str | None = None
        self._version_cache: str | None = None

    def _base_args(self) -> list[str]:
        args = [
            "--no-playlist",
            "--no-warnings",
            "--retries", "5",
            "--fragment-retries", "5",
            "--extractor-retries", "3",
            "--retry-sleep", "1",
            "--socket-timeout", "20",
        ]
        if self.bins.js_runtime and self.bins.js_runtime_kind == "deno":
            args += ["--js-runtimes", f"deno:{self.bins.js_runtime}"]
        if self.bins.ffmpeg_network:
            # See find_binaries(): the bundled static FFmpeg crashes on HTTPS input.
            args += ["--ffmpeg-location", str(Path(self.bins.ffmpeg_network).parent)]
        cookies = Path(self.cookies_file or os.environ.get("CLIPWRIGHT_YTDLP_COOKIES", "")).expanduser()
        if self.cookies_file or os.environ.get("CLIPWRIGHT_YTDLP_COOKIES"):
            if cookies.is_file():
                args += ["--cookies", str(cookies)]
        return args

    async def metadata(self, url: str, *, timeout: float = 90) -> dict[str, Any]:
        clean = validate_source_url(url)
        attempts: list[str | None] = [None]
        if _is_youtube(clean):
            attempts += ["web_embedded", "mweb"]
        errors: list[EngineError] = []
        for index, client in enumerate(attempts):
            if index:
                await asyncio.sleep(min(1.5 * index, 3.0))
            result = await self.runner.run(
                ytdlp_command(
                    self.bins,
                    [
                        *self._base_args(),
                        *self._client_args(client),
                        "--dump-single-json",
                        "--skip-download",
                        "--",
                        clean,
                    ],
                ),
                timeout=timeout,
            )
            if result.returncode != 0:
                error = map_ytdlp_error(result.stderr)
                errors.append(error)
                if error.retryable and error.code in (
                    "SOURCE_DOWNLOAD_BLOCKED",
                    "SOURCE_DOWNLOAD_FAILED",
                    "SOURCE_NETWORK",
                ):
                    continue
                raise error
            line = next((ln for ln in reversed(result.stdout.splitlines()) if ln.strip().startswith("{")), "")
            if not line:
                raise EngineError(
                    "SOURCE_METADATA_FAILED",
                    "The site returned no video information for that link.",
                    details={"stdoutTail": result.stdout[-1200:], "stderrTail": result.stderr[-1200:]},
                )
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EngineError(
                    "SOURCE_METADATA_FAILED", "The site returned video information that could not be read."
                ) from exc
            info = summarize_metadata(data)
            if info["duration_s"] and info["duration_s"] > 6 * 3600:
                raise EngineError("MEDIA_TOO_LONG", "This source is longer than 6 hours. Choose a shorter video.")
            if info.get("live_status") in ("is_live", "is_upcoming"):
                raise EngineError("SOURCE_LIVE", "Live streams cannot be analyzed. Import the finished video instead.")
            return info
        blocked = next((e for e in errors if e.code == "SOURCE_DOWNLOAD_BLOCKED"), None)
        chosen = blocked or errors[-1]
        chosen.details = {**(chosen.details or {}), "attempts": [e.code for e in errors]}
        raise chosen

    def _subtitle_files(self, out_dir: Path) -> list[Path]:
        suffixes = {".json3", ".vtt", ".srt", ".ass", ".ttml"}
        return sorted(p for p in out_dir.glob("sub.*") if p.is_file() and p.suffix.lower() in suffixes and p.stat().st_size > 0)

    async def download_subtitles(
        self,
        url: str,
        out_dir: Path,
        *,
        languages: list[str] | None = None,
        allow_auto: bool = True,
        cancel=None,
    ) -> list[Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        langs = ",".join(languages) if languages else "en.*,en"
        attempts: list[str | None] = [None]
        if _is_youtube(url):
            attempts += ["web_embedded", "mweb"]
        errors: list[EngineError] = []
        for index, client in enumerate(attempts):
            if cancel is not None and cancel.is_set():
                raise CancelledError()
            if index:
                await asyncio.sleep(min(1.0 * index, 2.0))
            for old in out_dir.glob("sub.*"):
                if old.is_file():
                    old.unlink(missing_ok=True)
            args = [
                *self._base_args(),
                *self._client_args(client),
                "--skip-download",
                "--write-subs",
                *(["--write-auto-subs"] if allow_auto else []),
                "--sub-langs", langs,
                "--sub-format", "json3/vtt/best",
                "-o", str(out_dir / "sub.%(ext)s"),
                "--", url,
            ]
            result = await self.runner.run(ytdlp_command(self.bins, args), cancel=cancel, timeout=180)
            files = self._subtitle_files(out_dir)
            if files:
                # yt-dlp can write one language and then fail on a second one
                # (usually HTTP 429). Keep the usable caption instead of
                # throwing it away and falling back to slow audio transcription.
                return files
            if result.returncode != 0:
                error = map_ytdlp_error(result.stderr)
                errors.append(error)
                if error.retryable and error.code in (
                    "SOURCE_DOWNLOAD_BLOCKED",
                    "SOURCE_DOWNLOAD_FAILED",
                    "SOURCE_NETWORK",
                ):
                    continue
                raise error
        if errors:
            blocked = next((e for e in errors if e.code == "SOURCE_DOWNLOAD_BLOCKED"), None)
            chosen = blocked or errors[-1]
            chosen.details = {**(chosen.details or {}), "attempts": [e.code for e in errors]}
            raise chosen
        return []

    async def download_audio(self, url: str, out_dir: Path, *, cancel=None) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        args = [
            *self._base_args(),
            "-f", "ba[abr<=96]/ba/worstaudio",
            "-o", str(out_dir / "audio.%(ext)s"),
            "--", url,
        ]
        result = await self.runner.run(ytdlp_command(self.bins, args), cancel=cancel, timeout=1800)
        if result.returncode != 0:
            raise map_ytdlp_error(result.stderr)
        candidates = [p for p in out_dir.glob("audio.*") if p.is_file() and p.stat().st_size > 0]
        if not candidates:
            raise EngineError("SOURCE_AUDIO_MISSING", "This video has no downloadable audio track.")
        return max(candidates, key=lambda p: p.stat().st_size)

    def _client_args(self, client: str | None) -> list[str]:
        if not client:
            return []
        return ["--extractor-args", f"youtube:player_client={client}"]

    def _clean_sections(self, out_dir: Path) -> None:
        for old in out_dir.glob("section.*"):
            if old.is_file():
                old.unlink(missing_ok=True)

    async def _download_section_once(
        self,
        url: str,
        out_dir: Path,
        *,
        start_s: float,
        end_s: float,
        max_height: int,
        client: str | None,
        progressive: bool,
        cancel=None,
    ) -> Path:
        def fmt(seconds: float) -> str:
            seconds = max(0.0, seconds)
            return f"{int(seconds // 3600)}:{int(seconds % 3600 // 60):02d}:{seconds % 60:06.3f}"

        section = f"*{fmt(start_s)}-{fmt(end_s)}"
        self._clean_sections(out_dir)
        args = [
            *self._base_args(),
            *self._client_args(client),
            "-f", _progressive_format(max_height) if progressive else _video_format(max_height),
            "--download-sections", section,
            "--no-force-keyframes-at-cuts",
            "--merge-output-format", "mp4",
            "-o", str(out_dir / "section.%(ext)s"),
            "--", url,
        ]
        result = await self.runner.run(ytdlp_command(self.bins, args), cancel=cancel, timeout=1800)
        if result.returncode != 0:
            raise map_ytdlp_error(result.stderr)
        candidates = [p for p in out_dir.glob("section.*") if p.suffix in (".mp4", ".mkv", ".webm")]
        if not candidates:
            raise EngineError("SOURCE_DOWNLOAD_FAILED", "The requested section was downloaded but no video file was produced.")
        return max(candidates, key=lambda p: p.stat().st_size)

    async def download_section(
        self,
        url: str,
        out_dir: Path,
        *,
        start_s: float,
        end_s: float,
        max_height: int = 1080,
        cancel=None,
    ) -> Path:
        """Download a padded section, with fresh extraction and client fallbacks.

        YouTube sometimes issues a 403 for one DASH URL/client while the same
        moment is still available through another client. Retrying with a new
        extraction (and, for YouTube, alternate clients) is far more reliable
        than reusing the failed URL. Preview caching in the API layer prevents
        this from being hit repeatedly for the same moment.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        attempts: list[tuple[str | None, bool]] = [(None, False)]
        if _is_youtube(url):
            # web_embedded often serves HTTPS HLS without a web PO token;
            # mweb is a second independent client/format path.
            attempts += [("web_embedded", False), ("mweb", True)]
        else:
            attempts.append((None, True))

        errors: list[EngineError] = []
        for index, (client, progressive) in enumerate(attempts):
            if cancel is not None and cancel.is_set():
                raise CancelledError()
            if index:
                await asyncio.sleep(min(1.5 * index, 3.0))
            try:
                return await self._download_section_once(
                    url,
                    out_dir,
                    start_s=start_s,
                    end_s=end_s,
                    max_height=max_height,
                    client=client,
                    progressive=progressive,
                    cancel=cancel,
                )
            except EngineError as exc:
                errors.append(exc)
                if not exc.retryable or exc.code not in (
                    "SOURCE_DOWNLOAD_BLOCKED",
                    "SOURCE_DOWNLOAD_FAILED",
                    "SOURCE_NETWORK",
                ):
                    raise

        # Last resort: yt-dlp's native downloader (no network FFmpeg), then cut
        # locally. This also covers clean machines with no system FFmpeg.
        try:
            return await self._download_full_and_cut(
                url, out_dir, start_s=start_s, end_s=end_s, max_height=max_height, cancel=cancel
            )
        except EngineError as exc:
            errors.append(exc)

        # Preserve the most useful error (blocked/auth first), with every
        # attempt summarized for diagnostics.
        blocked = next((e for e in errors if e.code == "SOURCE_DOWNLOAD_BLOCKED"), None)
        chosen = blocked or errors[-1]
        chosen.details = {**(chosen.details or {}), "attempts": [e.code for e in errors]}
        raise chosen

    async def _download_full_and_cut(
        self,
        url: str,
        out_dir: Path,
        *,
        start_s: float,
        end_s: float,
        max_height: int,
        client: str | None = None,
        cancel=None,
    ) -> Path:
        """Fallback for platforms without a network-capable system FFmpeg.

        Downloads a progressive stream with yt-dlp's native downloader (no FFmpeg
        networking), then trims the local file with the bundled FFmpeg.
        """
        full_dir = out_dir / "full"
        full_dir.mkdir(parents=True, exist_ok=True)
        fmt = f"b[height<={max_height}][vcodec^=avc1]/b[height<={max_height}]/b"
        args = [
            *self._base_args(),
            *self._client_args(client),
            "--downloader", "native",
            "--no-part",
            "-f", fmt,
            "-o", str(full_dir / "full.%(ext)s"),
            "--", url,
        ]
        result = await self.runner.run(ytdlp_command(self.bins, args), cancel=cancel, timeout=1800)
        if result.returncode != 0:
            raise map_ytdlp_error(result.stderr)
        fulls = [p for p in full_dir.glob("full.*") if p.is_file() and p.stat().st_size > 0]
        if not fulls:
            raise EngineError("SOURCE_DOWNLOAD_FAILED", "The video was downloaded but no playable file was produced.")
        full = max(fulls, key=lambda p: p.stat().st_size)
        output = out_dir / "section.mp4"
        duration = max(0.1, end_s - start_s)
        cut = await self.runner.run(
            [
                *ffmpeg_command(self.bins),
                "-hide_banner", "-y",
                "-ss", f"{max(0.0, start_s):.3f}",
                "-t", f"{duration:.3f}",
                "-i", str(full),
                "-c", "copy", "-avoid_negative_ts", "make_zero",
                str(output),
            ],
            cancel=cancel,
            timeout=600,
        )
        full.unlink(missing_ok=True)
        if cut.returncode != 0 or not output.exists() or output.stat().st_size == 0:
            raise EngineError("SOURCE_DOWNLOAD_FAILED", "The downloaded video could not be prepared for preview.")
        return output

    async def version(self) -> str:
        if self._version_cache is not None:
            return self._version_cache
        result = await self.runner.run(ytdlp_command(self.bins, ["--version"]), timeout=30)
        self._version_cache = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "unknown"
        return self._version_cache
