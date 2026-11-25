from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Any


from ...common.brand import ENGINE_VERSION, PROTOCOL_VERSION, PRODUCT_NAME
from ...common.errors import EngineError
from ...common.logging import redact_obj
from ...ingest.binaries import find_binaries
from ...common.resources import repo_root
from ...models.catalog import face_catalog, whisper_catalog
from ..params import (
    BinariesUpdateParams,
    Empty,
    HelloParams,
    JobIdParams,
    JobsListParams,
    ModelDownloadParams,
    ModelIdParams,
    SettingsGetParams,
    SettingsSetParams,
)
from ..registry import Registry


async def _version(cmd: list[str], runner, timeout: float = 20) -> str | None:
    try:
        result = await runner.run(cmd, timeout=timeout)
        line = (result.stdout or result.stderr).strip().splitlines()
        return line[0][:200] if line else None
    except Exception:
        return None


def register(registry: Registry) -> None:
    registry.add("engine.hello", HelloParams, hello)
    registry.add("engine.ping", Empty, ping)
    registry.add("engine.shutdown", Empty, shutdown)
    registry.add("hardware.detect", Empty, hardware_detect)
    registry.add("settings.get", SettingsGetParams, settings_get)
    registry.add("settings.set", SettingsSetParams, settings_set)
    registry.add("binaries.status", Empty, binaries_status)
    registry.add("binaries.update", BinariesUpdateParams, binaries_update)
    registry.add("models.list", Empty, models_list)
    registry.add("models.download", ModelDownloadParams, models_download)
    registry.add("models.verify", ModelIdParams, models_verify)
    registry.add("models.delete", ModelIdParams, models_delete)
    registry.add("diagnostics.export", Empty, diagnostics_export)
    registry.add("privacy.log", Empty, privacy_log)
    registry.add("privacy.clear", Empty, privacy_clear)
    registry.add("jobs.list", JobsListParams, jobs_list)
    registry.add("jobs.get", JobIdParams, jobs_get)
    registry.add("jobs.cancel", JobIdParams, jobs_cancel)
    registry.add("jobs.resume", JobIdParams, jobs_resume)


async def hello(app, params: HelloParams, secrets) -> dict[str, Any]:
    if params.protocolVersion != PROTOCOL_VERSION:
        raise EngineError(
            "ENGINE_PROTOCOL_MISMATCH",
            "The app and its media engine speak different protocol versions. Reinstall or update the app.",
            details={"engine": PROTOCOL_VERSION, "app": params.protocolVersion},
        )
    return {
        "engineVersion": ENGINE_VERSION,
        "protocolVersion": PROTOCOL_VERSION,
        "productName": PRODUCT_NAME,
        "capabilities": [
            "projects", "sources", "transcription.local", "transcription.cloud", "analysis",
            "discovery", "render", "providers", "models", "diagnostics", "media",
        ],
        "dataDir": str(app.ctx.paths.data_dir),
        "platform": sys.platform,
        "python": platform.python_version(),
        "appVersion": params.appVersion,
    }


async def ping(app, params: Empty, secrets) -> dict[str, Any]:
    return {"pong": True, "uptimeSeconds": round(time.monotonic() - app.started_at, 1)}


async def shutdown(app, params: Empty, secrets) -> dict[str, Any]:
    app.request_shutdown()
    return {"ok": True}


async def hardware_detect(app, params: Empty, secrets) -> dict[str, Any]:
    return await app.ctx.hardware.detect()


def _merged_settings(app) -> dict[str, Any]:
    from ..context import DEFAULT_SETTINGS

    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    for key, value in app.ctx.settings.all().items():
        if key in merged and isinstance(value, dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


async def settings_get(app, params: SettingsGetParams, secrets) -> dict[str, Any]:
    all_settings = _merged_settings(app)
    if params.key:
        return {"key": params.key, "value": all_settings.get(params.key)}
    all_settings["providers"] = {
        "defaultProfileId": app.ctx.settings.get("providers", {}).get("defaultProfileId")
        or app.ctx.providers.list()[0]["id"] if app.ctx.providers.list() else None
    }
    all_settings["dataDir"] = str(app.ctx.paths.data_dir)
    return {"settings": all_settings}


async def settings_set(app, params: SettingsSetParams, secrets) -> dict[str, Any]:
    if not isinstance(params.value, dict):
        raise EngineError("INVALID_PARAMS", "Settings values must be objects.")
    current = app.ctx.settings.get(params.key, {})
    if not isinstance(current, dict):
        current = {}
    merged = {**current, **params.value}
    app.ctx.settings.set(params.key, merged)
    if params.key == "downloads":
        app.ctx.ytdlp.cookies_file = merged.get("cookiesFile")
    return {"key": params.key, "value": merged}


async def _ytdlp_version(app) -> str | None:
    try:
        return await app.ctx.ytdlp.version()
    except Exception:
        return None


async def _version_for(cmd: list[str] | None, runner) -> str | None:
    return await _version(cmd, runner) if cmd else None


async def _value(value: str | None) -> str | None:
    return value


def _manifest_version(binary: str | None, name: str) -> str | None:
    """Read the pinned version without paying a 2 s yt-dlp startup."""
    if not binary:
        return None
    try:
        for parent in Path(binary).resolve().parents:
            manifest = parent / "MANIFEST.json"
            if not manifest.is_file():
                continue
            data = json.loads(manifest.read_text(encoding="utf-8"))
            for entries in (data.get("platforms") or {}).values():
                for entry in entries:
                    if entry.get("name") == name and entry.get("version"):
                        return str(entry["version"])
    except (OSError, ValueError, TypeError):
        return None
    return None


async def binaries_status(app, params: Empty, secrets) -> dict[str, Any]:
    bins = find_binaries(app.ctx.paths, repo_root())
    updater_file = app.ctx.paths.bin / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
    # These are independent processes. Running them sequentially made Settings
    # wait for ffmpeg, ffprobe, yt-dlp and Deno one after another. The bundled
    # downloader's version is in MANIFEST.json; only user-installed copies need
    # the (slow) --version probe.
    manifest_version = None if updater_file.exists() else _manifest_version(bins.ytdlp, "yt-dlp")
    ffmpeg_version, ffprobe_version, ytdlp_version, js_version = await asyncio.gather(
        _version_for([bins.ffmpeg, "-version"] if bins.ffmpeg else None, app.ctx.runner),
        _version_for([bins.ffprobe, "-version"] if bins.ffprobe else None, app.ctx.runner),
        _ytdlp_version(app) if manifest_version is None else _value(manifest_version),
        _version_for([bins.js_runtime, "--version"] if bins.js_runtime else None, app.ctx.runner),
    )
    return {
        "ffmpeg": {"path": bins.ffmpeg, "version": ffmpeg_version, "origin": bins.ffmpeg_origin},
        "ffprobe": {"path": bins.ffprobe, "version": ffprobe_version},
        "ytdlp": {
            "path": bins.ytdlp,
            "kind": bins.ytdlp_kind,
            "version": ytdlp_version,
            "origin": bins.ytdlp_origin,
            "userInstalled": updater_file.exists(),
            "userPath": str(updater_file) if updater_file.exists() else None,
        },
        "jsRuntime": {"path": bins.js_runtime, "kind": bins.js_runtime_kind, "version": js_version},
        "ytdlpHealthy": bool(bins.ytdlp),
        "jsRuntimeHealthy": bool(bins.js_runtime),
        "notes": (
            "A JavaScript runtime (Deno recommended) is needed for some YouTube formats. "
            "Install Deno or bundle it at build time."
            if not bins.js_runtime
            else ""
        ),
        "dataDir": str(app.ctx.paths.data_dir),
    }


async def binaries_update(app, params: BinariesUpdateParams, secrets) -> dict[str, Any]:
    if params.channel == "nightly":
        raise EngineError(
            "UPDATER_NIGHTLY_UNSUPPORTED",
            "Nightly downloader builds are not wired up in this build. Use the stable channel.",
        )
    api = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
    import httpx

    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers={"User-Agent": f"{PRODUCT_NAME}-updater"}) as client:
        try:
            release = (await client.get(api)).json()
        except Exception as exc:
            raise EngineError(
                "UPDATER_NETWORK", "The downloader update check failed. Check your connection.", retryable=True
            ) from exc
        tag = release.get("tag_name") or "unknown"
        asset_name = "yt-dlp.exe" if sys.platform == "win32" else ("yt-dlp_macos" if sys.platform == "darwin" else "yt-dlp_linux")
        assets = {a["name"]: a for a in release.get("assets") or []}
        if asset_name not in assets or "SHA2-256SUMS" not in assets:
            raise EngineError("UPDATER_ASSET_MISSING", "This platform has no official downloader build available.")
        tmp_dir = app.ctx.paths.tmp / f"ytdlp-{app.ctx.db.new_id()[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            sums = (await client.get(assets["SHA2-256SUMS"]["browser_download_url"])).text
            expected = None
            for line in sums.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == asset_name:
                    expected = parts[0]
                    break
            if not expected:
                raise EngineError("UPDATER_CHECKSUM_MISSING", "The downloader checksum file did not include this platform.")
            target = tmp_dir / asset_name
            digest = hashlib.sha256()
            with target.open("wb") as fh:
                async with client.stream("GET", assets[asset_name]["browser_download_url"]) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(512 * 1024):
                        fh.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != expected:
                raise EngineError("UPDATER_CHECKSUM_MISMATCH", "The downloader update failed its checksum and was discarded.")
            dest = app.ctx.paths.bin / asset_name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(dest))
            if sys.platform != "win32":
                os.chmod(dest, 0o755)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
    app.reload_binaries()
    return {
        "updated": True,
        "version": tag,
        "path": str(dest),
        "channel": params.channel,
        "message": "Downloader updated. Try the import again.",
    }


async def models_list(app, params: Empty, secrets) -> dict[str, Any]:
    listing = app.ctx.models.list()
    hardware = await app.ctx.hardware.detect()
    listing["recommended"] = {
        "low": ["tiny", "base", "small"],
        "balanced": ["small", "distil-small.en", "medium"],
        "performance": ["large-v3-turbo", "distil-large-v3", "large-v3"],
    }.get(hardware.get("recommendedProfile"), ["small"])
    listing["hardware"] = {
        "profile": hardware.get("recommendedProfile"),
        "ramBytes": hardware.get("ramBytes"),
        "cudaUsable": hardware.get("cudaUsable"),
    }
    return listing


async def models_download(app, params: ModelDownloadParams, secrets) -> dict[str, Any]:
    return await app.ctx.job_manager.start("model_download", params.model_dump(), None)


async def models_verify(app, params: ModelIdParams, secrets) -> dict[str, Any]:
    return await app.ctx.models.verify(params.modelId)


async def models_delete(app, params: ModelIdParams, secrets) -> dict[str, Any]:
    await app.ctx.models.delete(params.modelId)
    return {"ok": True, "modelId": params.modelId}


async def diagnostics_export(app, params: Empty, secrets) -> dict[str, Any]:
    out_dir = app.ctx.paths.data_dir / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"clipwright-diagnostics-{stamp}.zip"
    hardware = await app.ctx.hardware.detect()
    bins = await binaries_status(app, Empty(), {})
    settings = redact_obj(_merged_settings(app))
    jobs = app.ctx.jobs.list()
    providers = [
        {k: v for k, v in p.items() if k != "capabilities"}
        for p in app.ctx.providers.list()
    ]
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        if app.ctx.paths.log_path.exists():
            zf.write(app.ctx.paths.log_path, "logs/engine.log")
        zf.writestr("system.json", json.dumps({"hardware": hardware, "binaries": bins, "python": platform.python_version(), "engine": ENGINE_VERSION}, indent=2, default=str))
        zf.writestr("settings.json", json.dumps(settings, indent=2, default=str))
        zf.writestr("jobs.json", json.dumps([{k: v for k, v in j.items() if k not in ("checkpoint",)} for j in jobs], indent=2, default=str))
        zf.writestr("providers.json", json.dumps(providers, indent=2, default=str))
    return {"path": str(target), "bytes": target.stat().st_size, "note": "No API keys, media, or transcripts are included."}


async def jobs_list(app, params: JobsListParams, secrets) -> dict[str, Any]:
    return {"jobs": [job for job in app.ctx.jobs.list(params.projectId, params.activeOnly) if job]}


async def jobs_get(app, params: JobIdParams, secrets) -> dict[str, Any]:
    job = app.ctx.jobs.get(params.jobId)
    if not job:
        raise EngineError("JOB_NOT_FOUND", "That job does not exist.")
    job["events"] = app.ctx.jobs.events(params.jobId)
    return {"job": job}


async def jobs_cancel(app, params: JobIdParams, secrets) -> dict[str, Any]:
    return await app.ctx.job_manager.cancel(params.jobId)


async def jobs_resume(app, params: JobIdParams, secrets) -> dict[str, Any]:
    return await app.ctx.job_manager.resume(params.jobId, secrets)


async def privacy_log(app, params: Empty, secrets) -> dict[str, Any]:
    return {
        "entries": app.ctx.request_log.list(),
        "note": (
            "Metadata only: time, provider, model, operation, approximate tokens and the categories of data sent. "
            "Transcript text, audio and API keys are never written to this log."
        ),
    }


async def privacy_clear(app, params: Empty, secrets) -> dict[str, Any]:
    app.ctx.request_log.clear()
    return {"ok": True}
