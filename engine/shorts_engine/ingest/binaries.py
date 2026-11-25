from __future__ import annotations

import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from ..common.paths import AppPaths


@dataclass
class BinaryPaths:
    ffmpeg: str | None
    ffprobe: str | None
    ytdlp: str | None
    ytdlp_kind: str
    js_runtime: str | None
    js_runtime_kind: str | None
    ffmpeg_origin: str
    ytdlp_origin: str
    ffmpeg_network: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _platform_dir() -> str:
    if sys.platform == "win32":
        return "win-x64"
    if sys.platform == "darwin":
        return "mac-arm64" if os.uname().machine == "arm64" else "mac-x64"
    return "linux-x64"


def find_binaries(paths: AppPaths, repo_root: Path | None = None) -> BinaryPaths:
    exe = ".exe" if sys.platform == "win32" else ""
    roots = [paths.bin]
    if repo_root:
        roots += [repo_root / "resources/bin" / _platform_dir(), repo_root / "resources/bin"]
    roots += [Path("/usr/bin"), Path("/usr/local/bin"), Path.home() / ".local/bin"]

    def find(name: str) -> tuple[str | None, str]:
        for root in roots:
            candidate = root / f"{name}{exe}"
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate), str(root)
        resolved = shutil.which(name)
        return (resolved, "PATH") if resolved else (None, "")

    ffmpeg, ffmpeg_origin = find("ffmpeg")
    ffprobe, _ = find("ffprobe")
    ytdlp, ytdlp_origin = find("yt-dlp")
    ytdlp_kind = "binary" if ytdlp else "none"
    if not ytdlp:
        try:
            import yt_dlp  # noqa: F401

            ytdlp = sys.executable
            ytdlp_kind = "python-module"
            ytdlp_origin = f"python ({Path(sys.executable).name})"
        except ImportError:
            pass
    # The bundled johnvansickle FFmpeg 7.0.2 segfaults when opening HTTPS inputs.
    # Prefer a distro FFmpeg for yt-dlp's network downloads when one exists; local
    # rendering still uses the bundled binary. A native full-download fallback in
    # YtDlp covers clean machines with no system FFmpeg.
    ffmpeg_network = None
    bundled_real = Path(ffmpeg).resolve() if ffmpeg else None
    for candidate in (Path("/usr/bin/ffmpeg"), Path("/usr/local/bin/ffmpeg")):
        if candidate.is_file() and os.access(candidate, os.X_OK) and candidate.resolve() != bundled_real:
            ffmpeg_network = str(candidate)
            break
    js_runtime, js_kind = None, None
    for name in ("deno", "node", "qjs", "bun"):
        found, _ = find(name)
        if found:
            js_runtime, js_kind = found, name
            break
    return BinaryPaths(
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        ytdlp=ytdlp,
        ytdlp_kind=ytdlp_kind,
        js_runtime=js_runtime,
        js_runtime_kind=js_kind,
        ffmpeg_origin=ffmpeg_origin,
        ytdlp_origin=ytdlp_origin,
        ffmpeg_network=ffmpeg_network,
    )


def ytdlp_command(bins: BinaryPaths, args: list[str]) -> list[str]:
    if not bins.ytdlp:
        from ..common.errors import EngineError

        raise EngineError(
            "DOWNLOADER_MISSING",
            "The video downloader is not installed. Use a local file, or run scripts/fetch-binaries.",
            retryable=False,
        )
    if bins.ytdlp_kind == "python-module":
        return [bins.ytdlp, "-m", "yt_dlp", *args]
    return [bins.ytdlp, *args]


def ffmpeg_command(bins: BinaryPaths) -> list[str]:
    if not bins.ffmpeg:
        from ..common.errors import EngineError

        raise EngineError("FFMPEG_MISSING", "FFmpeg was not found. Reinstall the app or install FFmpeg.")
    return [bins.ffmpeg]


def ffprobe_command(bins: BinaryPaths) -> list[str]:
    if not bins.ffprobe:
        from ..common.errors import EngineError

        raise EngineError("FFMPEG_MISSING", "ffprobe was not found. Reinstall the app or install FFmpeg.")
    return [bins.ffprobe]
