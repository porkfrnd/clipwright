from __future__ import annotations

import asyncio
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from ..common.brand import ENGINE_VERSION, PRODUCT_NAME, PROTOCOL_VERSION
from ..common.errors import EngineError
from ..common.logging import redact_obj, redact_text, setup_logging
from ..common.paths import AppPaths
from ..storage.db import now
from .context import build_context
from .jobs import JobManager
from .methods import analysis as analysis_methods
from .methods import captions as caption_methods
from .methods import projects as project_methods
from .methods import providers as provider_methods
from .methods import render as render_methods
from .methods import system as system_methods
from .methods import timeline as timeline_methods
from .registry import Registry
from .schemas import ErrorPayload, Event, Request, Response


class EngineApp:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.paths = AppPaths(data_dir)
        self.log = setup_logging(self.paths.log_path)
        self.ctx = build_context(self.paths)
        self.registry = Registry()
        self.started_at = time.monotonic()
        self._write_lock = asyncio.Lock()
        self._shutdown = asyncio.Event()
        self.job_manager = JobManager(self.ctx, self.emit_sync)
        self.ctx.job_manager = self.job_manager
        system_methods.register(self.registry)
        project_methods.register(self.registry)
        provider_methods.register(self.registry)
        analysis_methods.register(self.registry)
        caption_methods.register(self.registry)
        timeline_methods.register(self.registry)
        render_methods.register(self.registry)
        from .job_handlers import register_jobs

        register_jobs(self)
        self.log.info(
            "%s engine %s starting (protocol %s) data=%s",
            PRODUCT_NAME,
            ENGINE_VERSION,
            PROTOCOL_VERSION,
            self.paths.data_dir,
        )

    def reload_binaries(self) -> None:
        from ..common.proc import ProcessRunner
        from ..common.resources import repo_root
        from ..hardware.detect import HardwareDetector
        from ..ingest.audio import AudioTools
        from ..ingest.binaries import find_binaries
        from ..ingest.probe import Prober
        from ..ingest.ytdlp import YtDlp
        from ..render.encoder import EncoderProbe

        bins = find_binaries(self.paths, repo_root())
        self.ctx.bins = bins
        self.ctx.prober = Prober(bins, self.ctx.runner)
        self.ctx.audio = AudioTools(bins, self.ctx.runner)
        cookies_file = self.ctx.ytdlp.cookies_file
        self.ctx.ytdlp = YtDlp(bins, self.ctx.runner)
        self.ctx.ytdlp.cookies_file = cookies_file
        self.ctx.encoder_probe = EncoderProbe(bins, self.ctx.runner)
        self.ctx.hardware = HardwareDetector(self.paths, bins, self.ctx.runner)
        self.ctx.render.bins = bins
        self.ctx.render.prober = self.ctx.prober
        self.ctx.render.audio = self.ctx.audio
        self.ctx.render.ytdlp = self.ctx.ytdlp
        self.ctx.render.encoder_probe = self.ctx.encoder_probe
        self.ctx.transcription.audio = self.ctx.audio
        self.log.info("Binaries reloaded: ffmpeg=%s ytdlp=%s", bins.ffmpeg, bins.ytdlp)

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def emit_sync(self, method: str, params: dict[str, Any]) -> None:
        payload = Event(method=method, params=redact_obj(params)).model_dump(mode="json")
        try:
            asyncio.get_running_loop().create_task(self._write(payload))
        except RuntimeError:
            sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()

    async def _write(self, payload: dict[str, Any]) -> None:
        async with self._write_lock:
            sys.stdout.write(json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n")
            sys.stdout.flush()

    async def handle_request(self, line: str) -> None:
        request: Request | None = None
        try:
            raw = json.loads(line)
            request = Request.model_validate(raw)
            if request.v != 1:
                raise EngineError(
                    "ENGINE_PROTOCOL_MISMATCH",
                    "This app and engine speak different protocol versions.",
                    details={"engine": 1, "app": request.v},
                )
            result = await self.registry.dispatch(request.method, request.params, request.secrets, self)
            response = Response(id=request.id, result=result)
        except EngineError as exc:
            self.log.warning("request failed: %s", exc.message)
            response = Response(
                id=request.id if request else "unknown",
                error=ErrorPayload.from_error(exc),
            )
        except Exception as exc:  # noqa: BLE001
            self.log.error("unhandled request error: %s", traceback.format_exc())
            response = Response(
                id=request.id if request else "unknown",
                error=ErrorPayload(
                    code="INTERNAL_ERROR",
                    message="The engine hit an unexpected problem. Details are in the log.",
                    details={"error": redact_text(str(exc))[:400]},
                ),
            )
        await self._write(response.model_dump(mode="json", exclude_none=True))

    async def run_stdio(self) -> int:
        self.log.info("stdio protocol ready")
        loop = asyncio.get_running_loop()
        while not self._shutdown.is_set():
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            if not line.strip():
                continue
            asyncio.create_task(self.handle_request(line))
        self._shutdown.set()
        try:
            await asyncio.wait_for(self.ctx.runner.kill_all(), timeout=5)
        except Exception:
            pass
        self.ctx.db.close()
        return 0

    async def run_cli(self, job_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """Test/CLI entry point that runs a job inline without stdio."""
        result_holder: dict[str, Any] = {}

        def emit(method: str, payload: dict[str, Any]) -> None:
            if method == "job.result":
                result_holder.update(payload)

        self.job_manager.emit = emit  # type: ignore[assignment]
        started = await self.job_manager.start(job_type, params, params.get("projectId"))
        job_id = started["jobId"]
        task = self.job_manager.tasks.get(job_id)
        if task:
            await task
        return {"job": self.ctx.jobs.get(job_id), "result": result_holder}
