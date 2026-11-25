from __future__ import annotations

from pathlib import Path
from typing import Any

from .ass import escape_filter_path

WIDTH = 1080
HEIGHT = 1920


def framing_filter(framing: dict[str, Any], duration: float) -> str:
    layout = framing.get("layout") or "fill"
    zoom = max(1.0, min(2.0, float(framing.get("zoom") or 1.0)))
    if layout == "blur":
        # Blur a quarter-resolution background, then upscale it. A full-frame
        # gblur at 1080x1920 is one of the most expensive preview/export filters;
        # the downscale keeps the same visual result at a fraction of the work.
        blur_w, blur_h = WIDTH // 2, HEIGHT // 2
        bg = (
            f"scale={blur_w}:{blur_h}:force_original_aspect_ratio=increase,"
            f"crop={blur_w}:{blur_h},gblur=sigma=19,scale={WIDTH}:{HEIGHT}"
        )
        fg = f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease"
        return f"split=2[bg][fg];[bg]{bg}[bgv];[fg]{fg}[fgv];[bgv][fgv]overlay=(W-w)/2:(H-h)/2"
    if layout == "manual":
        manual = framing.get("manual") or {}
        x = max(0.0, min(1.0, float(manual.get("x") or 0.5)))
        y = max(0.0, min(1.0, float(manual.get("y") or 0.5)))
        w = max(0.05, min(1.0, float(manual.get("w") or 1.0)))
        h = max(0.05, min(1.0, float(manual.get("h") or 1.0)))
        return (
            f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}-iw*{w:.4f}/2:ih*{y:.4f}-ih*{h:.4f}/2,"
            f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT}"
        )
    # fill and center share the same geometry; center is explicit, fill is the default cover crop.
    scale_w = int(WIDTH * zoom)
    scale_h = int(HEIGHT * zoom)
    return (
        f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT}:(iw-{WIDTH})/2:(ih-{HEIGHT})/2"
    )


def build_video_chain(
    *,
    framing: dict[str, Any],
    subtitles: dict[str, Any],
    effects: dict[str, Any],
    duration: float,
    ass_path: Path | None,
    fonts_dir: Path | None,
    source_fps: float | None = None,
) -> str:
    chain = framing_filter(framing, duration)
    # The target is 30 fps. If the source is already ~30 fps, ffmpeg's fps
    # filter only copies frames; skip it and avoid a full extra filter pass.
    if source_fps is None or source_fps < 29.5 or source_fps > 30.5:
        chain += ",fps=30"
    if subtitles.get("enabled", True) and ass_path:
        fonts = f":fontsdir='{escape_filter_path(fonts_dir)}'" if fonts_dir else ""
        chain += f",ass=filename='{escape_filter_path(ass_path)}'{fonts}"
    if effects.get("cinematic"):
        chain += ",eq=contrast=1.06:saturation=0.94:brightness=-0.01,vignette=PI/5"
    if effects.get("fade", True):
        chain += f",fade=t=in:st=0:d=0.25,fade=t=out:st={max(0.0, duration - 0.3):.3f}:d=0.3"
    if effects.get("progressBar"):
        chain += (
            f",drawbox=x=0:y=ih-14:w=iw*t/{max(0.1, duration):.3f}:h=14:"
            "color=0xE8C77B@0.85:t=fill"
        )
    chain += ",setsar=1,format=yuv420p[vout]"
    return chain


def build_audio_chain(
    *,
    audio: dict[str, Any],
    measured: dict[str, float] | None,
    has_music: bool,
    input_index: int,
    music_index: int,
    duration: float,
    input_label: str | None = None,
) -> tuple[list[str], str]:
    """Return (extra filter chains, final audio label)."""
    target_i = float(audio.get("loudnessTarget", -14.0))
    target_tp = float(audio.get("truePeak", -1.5))
    filters: list[str] = []
    if audio.get("denoise"):
        filters.append("afftdn=nf=-25")
    if audio.get("voiceEnhance"):
        filters.append(
            "highpass=f=80,lowpass=f=12000,"
            "acompressor=threshold=0.1:ratio=3:attack=5:release=120:makeup=1"
        )
    loudnorm = f"loudnorm=I={target_i}:TP={target_tp}:LRA=11"
    if measured:
        required = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        if all(k in measured for k in required):
            loudnorm += (
                f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}:linear=true"
            )
    loudnorm += ":print_format=summary"
    filters.append(loudnorm)
    filters.append("aresample=48000")
    base = ",".join(filters)
    label = input_label or f"[{input_index}:a]"
    if not has_music:
        return [f"{label}{base}[aout]"], "[aout]"
    music_gain = float(audio.get("musicGainDb", -18.0))
    chains = [
        f"{label}{base}[voice0]",
        "[voice0]asplit=2[voice][side]",
        (
            f"[{music_index}:a]volume={music_gain}dB,"
            f"afade=t=in:st=0:d=1.0,afade=t=out:st={max(0.0, duration - 1.5):.3f}:d=1.5[music]"
        ),
        (
            "[music][side]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=280[ducked]"
        ),
        "[voice][ducked]amix=inputs=2:duration=first:normalize=0[aout]",
    ]
    return chains, "[aout]"


def build_ffmpeg_command(
    *,
    ffmpeg: list[str],
    source: Path,
    start_s: float,
    duration: float,
    output: Path,
    encoder_args: list[str],
    has_audio: bool,
    music_path: Path | None,
    framing: dict[str, Any],
    subtitles: dict[str, Any],
    effects: dict[str, Any],
    audio: dict[str, Any],
    ass_path: Path | None,
    fonts_dir: Path | None,
    measured: dict[str, float] | None,
    source_fps: float | None,
    timeline: dict[str, Any] | None = None,
) -> list[str]:
    args = [*ffmpeg, "-hide_banner", "-nostdin", "-y", "-ss", f"{start_s:.3f}", "-t", f"{duration:.3f}", "-i", str(source)]
    music_index = None
    silence_index = None
    if music_path:
        args += ["-i", str(music_path)]
        music_index = 1
    if not has_audio:
        silence_index = 2 if music_path else 1
        args += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    video_chain = build_video_chain(
        framing=framing,
        subtitles=subtitles,
        effects=effects,
        duration=duration,
        ass_path=ass_path,
        fonts_dir=fonts_dir,
        source_fps=source_fps,
    )
    audio_input = 0 if has_audio else silence_index or 1
    video_parts: list[str] = []
    audio_parts: list[str] = []
    video_input = "[0:v]"
    audio_label_override: str | None = None
    keep_ranges = (timeline or {}).get("keepRanges") or []
    if timeline and len(keep_ranges) > 1:
        fade = max(0.005, min(float(timeline.get("fadeS") or 0.03), 0.06))
        video_labels: list[str] = []
        audio_labels: list[str] = []
        for index, keep in enumerate(keep_ranges):
            begin = max(0.0, float(keep["startS"]))
            finish = max(begin + 0.05, float(keep["endS"]))
            length = finish - begin
            video_parts.append(f"[0:v]trim=start={begin:.3f}:end={finish:.3f},setpts=PTS-STARTPTS[v{index}]")
            video_labels.append(f"[v{index}]")
            if has_audio:
                edge = min(fade, max(0.005, length / 4))
                audio_parts.append(
                    f"[0:a]atrim=start={begin:.3f}:end={finish:.3f},asetpts=PTS-STARTPTS,"
                    f"afade=t=in:st=0:d={edge:.3f},afade=t=out:st={max(0.0, length - edge):.3f}:d={edge:.3f}[a{index}]"
                )
                audio_labels.append(f"[a{index}]")
        if video_labels:
            video_parts.append("".join(video_labels) + f"concat=n={len(video_labels)}:v=1:a=0[vbase]")
            video_input = "[vbase]"
        if audio_labels:
            audio_parts.append("".join(audio_labels) + f"concat=n={len(audio_labels)}:v=0:a=1[acat]")
            audio_label_override = "[acat]"
    audio_chains, audio_label = build_audio_chain(
        audio=audio,
        measured=measured,
        has_music=bool(music_path),
        input_index=audio_input,
        music_index=music_index or 1,
        duration=duration,
        input_label=audio_label_override,
    )
    filter_complex = ";".join([*video_parts, f"{video_input}{video_chain}", *audio_parts, *audio_chains])
    args += [
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", audio_label,
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        "-t", f"{duration:.3f}",
        str(output),
    ]
    return args


def parse_progress_line(line: str, duration: float) -> float | None:
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    if key not in ("out_time_ms", "out_time_us", "out_time"):
        return None
    try:
        if key == "out_time":
            parts = value.strip().split(":")
            seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        else:
            seconds = float(value) / 1_000_000
    except (ValueError, IndexError):
        return None
    if duration <= 0:
        return None
    return max(0.0, min(0.995, seconds / duration))
