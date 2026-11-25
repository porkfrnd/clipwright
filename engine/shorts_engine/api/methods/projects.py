from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import os
import shutil
from pathlib import Path


from ...common.errors import EngineError
from ...ingest.validate import validate_source_url
from ..params import (
    Empty,
    FetchPreviewParams,
    ImportFileParams,
    ImportUrlParams,
    MediaResolveParams,
    PresetDeleteParams,
    PresetSaveParams,
    ProjectCreateParams,
    ProjectIdParams,
    ProjectRenameParams,
    SourceAuthorizationParams,
    SourceIdParams,
)
from ..registry import Registry


def register(registry: Registry) -> None:
    registry.add("project.create", ProjectCreateParams, project_create)
    registry.add("project.list", Empty, project_list)
    registry.add("project.open", ProjectIdParams, project_open)
    registry.add("project.delete", ProjectIdParams, project_delete)
    registry.add("project.rename", ProjectRenameParams, project_rename)
    registry.add("preset.list", Empty, preset_list)
    registry.add("preset.save", PresetSaveParams, preset_save)
    registry.add("preset.delete", PresetDeleteParams, preset_delete)
    registry.add("source.import_file", ImportFileParams, import_file)
    registry.add("source.import_url", ImportUrlParams, import_url)
    registry.add("source.get", SourceIdParams, source_get)
    registry.add("source.probe", SourceIdParams, source_probe)
    registry.add("source.preview", SourceIdParams, source_preview)
    registry.add("source.fetch_preview", FetchPreviewParams, source_fetch_preview)
    registry.add("source.set_authorization", SourceAuthorizationParams, source_set_authorization)
    registry.add("media.resolve", MediaResolveParams, media_resolve)


def _fast_hash(path: Path) -> str:
    stat = path.stat()
    h = hashlib.sha256()
    h.update(str(stat.st_size).encode())
    h.update(str(int(stat.st_mtime)).encode())
    with path.open("rb") as fh:
        h.update(fh.read(1024 * 1024))
    return h.hexdigest()


async def project_create(app, params: ProjectCreateParams, secrets) -> dict[str, str]:
    project = app.ctx.projects.create(params.name)
    return {"project": project}


async def project_list(app, params: Empty, secrets) -> dict:
    return {"projects": app.ctx.projects.list()}


async def project_open(app, params: ProjectIdParams, secrets) -> dict:
    project = app.ctx.projects.get(params.projectId)
    if not project:
        raise EngineError("PROJECT_NOT_FOUND", "That project no longer exists.")
    app.ctx.projects.touch(params.projectId, opened=True)
    selections = app.ctx.selections.list(params.projectId)
    detailed = []
    for selection in selections:
        candidate = app.ctx.candidates.get(selection["candidateId"])
        if not candidate:
            continue
        detailed.append(
            {
                **selection,
                "candidate": candidate,
                "edit": app.ctx.edits.get(selection["id"]),
            }
        )
    sources = project.get("sources", [])
    return {
        "project": project,
        "selections": detailed,
        "sources": sources,
        "presets": app.ctx.presets.list(),
        "exports": app.ctx.exports.list(params.projectId),
        "jobs": app.ctx.jobs.list(params.projectId),
    }


async def project_delete(app, params: ProjectIdParams, secrets) -> dict:
    app.ctx.projects.delete(params.projectId)
    return {"ok": True}


async def project_rename(app, params: ProjectRenameParams, secrets) -> dict:
    app.ctx.projects.rename(params.projectId, params.name)
    return {"project": app.ctx.projects.get(params.projectId)}


async def preset_list(app, params: Empty, secrets) -> dict:
    return {"presets": app.ctx.presets.list()}


async def preset_save(app, params: PresetSaveParams, secrets) -> dict:
    try:
        preset = app.ctx.presets.save(params.name, params.settings, params.presetId)
    except ValueError as exc:
        raise EngineError("PRESET_BUILTIN", str(exc)) from exc
    return {"preset": preset}


async def preset_delete(app, params: PresetDeleteParams, secrets) -> dict:
    app.ctx.presets.delete(params.presetId)
    return {"ok": True}


async def import_file(app, params: ImportFileParams, secrets) -> dict:
    path = Path(params.path).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise EngineError("FILE_NOT_FOUND", "That file could not be found. Choose it again.")
    if path.stat().st_size > 32 * 1024**3:
        raise EngineError("FILE_TOO_LARGE", "That file is larger than 32 GB. Trim it first.")
    info = await app.ctx.prober.probe(path)
    project = app.ctx.projects.get(params.projectId)
    if not project:
        raise EngineError("PROJECT_NOT_FOUND", "That project no longer exists.")
    content_hash = _fast_hash(path)
    title = info.get("title") or path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    source = app.ctx.sources.create(
        params.projectId,
        kind="file",
        local_path=str(path),
        content_hash=content_hash,
        title=title,
        duration_s=info["duration_s"],
        width=info["width"],
        height=info["height"],
        fps=info["fps"],
        language=info.get("language"),
        metadata={"probe": {k: info[k] for k in ("format_name", "video_codec", "audio_codec", "size_bytes")}},
        authorization_ack_at=params.authorizationAckAt,
    )
    app.ctx.projects.touch(params.projectId)
    return {"source": source, "probe": {k: v for k, v in info.items() if k != "raw"}}


async def import_url(app, params: ImportUrlParams, secrets) -> dict:
    url = validate_source_url(params.url)
    project = app.ctx.projects.get(params.projectId)
    if not project:
        raise EngineError("PROJECT_NOT_FOUND", "That project no longer exists.")
    info = await app.ctx.ytdlp.metadata(url)
    content_hash = hashlib.sha256((info.get("webpage_url") or url).encode()).hexdigest()
    source = app.ctx.sources.create(
        params.projectId,
        kind="url",
        url=url,
        content_hash=content_hash,
        title=info["title"],
        channel=info["channel"],
        duration_s=info["duration_s"],
        width=info["width"],
        height=info["height"],
        fps=info["fps"],
        language=info.get("language"),
        metadata={**info, "requestedUrl": url},
        authorization_ack_at=params.authorizationAckAt,
    )
    thumbnail_url = info.get("thumbnail")
    if thumbnail_url:
        await _download_thumbnail(app, source["id"], thumbnail_url)
    app.ctx.projects.touch(params.projectId)
    return {"source": app.ctx.sources.get(source["id"]), "metadata": info}


async def _download_thumbnail(app, source_id: str, url: str) -> None:
    if not url.startswith("https://"):
        return
    dest_dir = app.ctx.paths.assets / source_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "thumbnail.jpg"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                total = 0
                with dest.open("wb") as fh:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        total += len(chunk)
                        if total > 3 * 1024 * 1024:
                            raise ValueError("thumbnail too large")
                        fh.write(chunk)
        app.ctx.assets.add(
            source_id, "thumb", str(dest), bytes_=dest.stat().st_size, pinned=True, meta={"origin": "site thumbnail"}
        )
    except Exception:
        dest.unlink(missing_ok=True)


async def source_get(app, params: SourceIdParams, secrets) -> dict:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    return {"source": source, "assets": app.ctx.assets.for_source(params.sourceId)}


async def source_probe(app, params: SourceIdParams, secrets) -> dict:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    if source["kind"] != "file":
        return {"source": source}
    path = Path(source.get("localPath") or "")
    info = await app.ctx.prober.probe(path, fresh=True)
    app.ctx.sources.update(
        params.sourceId,
        duration_s=info["duration_s"],
        width=info["width"],
        height=info["height"],
        fps=info["fps"],
    )
    return {"source": app.ctx.sources.get(params.sourceId), "probe": {k: v for k, v in info.items() if k != "raw"}}


async def source_preview(app, params: SourceIdParams, secrets) -> dict:
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    if source["kind"] != "file":
        previews = [a for a in app.ctx.assets.for_source(params.sourceId, "preview") if Path(a["path"]).exists()]
        return {"path": previews[0]["path"] if previews else None, "source": source}
    path = Path(source.get("localPath") or "")
    if not path.exists():
        raise EngineError("SOURCE_MISSING", "The original file has moved. Re-import it.")
    return {"path": str(path), "source": source}


async def source_fetch_preview(app, params: FetchPreviewParams, secrets) -> dict:
    if params.endS <= params.startS:
        raise EngineError("INVALID_RANGE", "The preview range is invalid.")
    if params.endS - params.startS > 120:
        raise EngineError("PREVIEW_TOO_LONG", "Previews are limited to two minutes.")
    source = app.ctx.sources.get(params.sourceId)
    if not source:
        raise EngineError("SOURCE_NOT_FOUND", "That source no longer exists.")
    if source["kind"] == "file":
        path = Path(source.get("localPath") or "")
        if not path.exists():
            raise EngineError("SOURCE_MISSING", "The original file has moved. Re-import it.")
        return {"path": str(path), "startS": params.startS, "endS": params.endS, "kind": "file"}
    cached = _cached_preview(app, params)
    if cached:
        return cached
    if not source.get("url"):
        raise EngineError("SOURCE_MISSING", "This source cannot be previewed.")
    # Compare and Studio can ask for the same section at the same time. Without
    # a per-range lock both requests miss the cache, download the same bytes, and
    # create duplicate assets. Normalize to the cache's half-second tolerance.
    key = f"{params.sourceId}:{round(params.startS * 2) / 2:.1f}:{round(params.endS * 2) / 2:.1f}"
    lock = app.ctx.preview_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        app.ctx.preview_locks[key] = lock
    try:
        async with lock:
            cached = _cached_preview(app, params)
            if cached:
                return cached
            req_start = max(0.0, params.startS - 1.0)
            req_end = min(float(source.get("durationS") or params.endS + 1), params.endS + 1.0)
            tmp = app.ctx.paths.tmp / f"preview-{app.ctx.db.new_id()[:8]}"
            tmp.mkdir(parents=True, exist_ok=True)
            try:
                section = await app.ctx.ytdlp.download_section(
                    source["url"], tmp, start_s=req_start, end_s=req_end, max_height=360
                )
                dest = app.ctx.paths.assets / source["id"] / f"preview-{app.ctx.db.new_id()[:8]}{section.suffix}"
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(section), dest)
                app.ctx.assets.add(
                    source["id"],
                    "preview",
                    str(dest),
                    start_s=req_start,
                    end_s=req_end,
                    bytes_=dest.stat().st_size,
                    meta={"requestedStart": params.startS, "requestedEnd": params.endS},
                )
                return {"path": str(dest), "startS": req_start, "endS": req_end, "kind": "url", "cached": False}
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
    finally:
        if not lock.locked() and app.ctx.preview_locks.get(key) is lock:
            app.ctx.preview_locks.pop(key, None)


def _cached_preview(app, params: FetchPreviewParams) -> dict | None:
    for asset in app.ctx.assets.for_source(params.sourceId, "preview"):
        meta = asset.get("meta") or {}
        same_start = abs(float(meta.get("requestedStart", -99)) - params.startS) < 0.5
        same_end = abs(float(meta.get("requestedEnd", -99)) - params.endS) < 0.5
        if same_start and same_end and Path(asset["path"]).exists():
            return {
                "path": asset["path"],
                "startS": float(asset.get("startS") or params.startS),
                "endS": float(asset.get("endS") or params.endS),
                "kind": "url",
                "cached": True,
            }
    return None


async def source_set_authorization(app, params: SourceAuthorizationParams, secrets) -> dict:
    app.ctx.sources.update(params.sourceId, authorization_ack_at=params.authorizationAckAt)
    return {"ok": True, "source": app.ctx.sources.get(params.sourceId)}


def _mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if mime:
        return mime
    return {".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm", ".mov": "video/quicktime"}.get(
        path.suffix.lower(), "application/octet-stream"
    )


async def media_resolve(app, params: MediaResolveParams, secrets) -> dict:
    asset = app.ctx.assets.get(params.assetId)
    if not asset:
        raise EngineError("ASSET_NOT_FOUND", "That media asset is not available.")
    path = Path(asset["path"]).resolve()
    if not path.exists():
        raise EngineError("ASSET_MISSING", "That media asset file is missing.")
    return {"path": str(path), "mime": _mime_for(path), "startS": asset.get("startS"), "endS": asset.get("endS")}
