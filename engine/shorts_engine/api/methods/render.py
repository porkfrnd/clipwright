from __future__ import annotations

from pathlib import Path

from ...common.errors import EngineError
from ..params import RenderQueueParams, RenderStartParams
from ..registry import Registry


def register(registry: Registry) -> None:
    registry.add("render.start", RenderStartParams, render_start)
    registry.add("render.queue", RenderQueueParams, render_queue)


async def render_start(app, params: RenderStartParams, secrets) -> dict:
    project = app.ctx.projects.get(params.projectId)
    if not project:
        raise EngineError("PROJECT_NOT_FOUND", "That project no longer exists.")
    selections = {s["id"] for s in app.ctx.selections.list(params.projectId)}
    for selection_id in params.selectionIds:
        if selection_id not in selections:
            raise EngineError("SELECTION_NOT_FOUND", "One of the clips is no longer selected in this project.")
    defaults = app.ctx.settings.get("render", {})
    output_dir = params.outputDir or defaults.get("outputDir")
    if not output_dir:
        raise EngineError("OUTPUT_REQUIRED", "Choose an output folder.")
    path = Path(output_dir).expanduser()
    if not path.is_absolute():
        raise EngineError("OUTPUT_INVALID", "Choose an absolute output folder.")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".clipwright-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise EngineError("OUTPUT_NOT_WRITABLE", "That output folder cannot be written to.", details={"error": str(exc)[:200]}) from exc
    job = await app.ctx.job_manager.start(
        "render",
        {
            "projectId": params.projectId,
            "selectionIds": params.selectionIds,
            "outputDir": str(path),
            "quality": params.quality,
            "preferHardware": params.preferHardware,
            "filenameTemplate": params.filenameTemplate or defaults.get("filenameTemplate", "{title}-{index}-{start}"),
        },
        params.projectId,
        secrets,
    )
    return job


async def render_queue(app, params: RenderQueueParams, secrets) -> dict:
    return {"exports": app.ctx.exports.list(params.projectId)}
