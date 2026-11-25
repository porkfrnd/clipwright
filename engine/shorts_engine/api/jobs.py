from __future__ import annotations

import asyncio
import shutil
import time
import traceback
from typing import Any, Awaitable, Callable

from ..common.errors import CancelledError, EngineError, RateLimited
from ..storage.repos import JobRepo
from .context import AppContext

JobHandler = Callable[["JobContext", dict[str, Any]], Awaitable[dict[str, Any]]]


class JobContext:
    def __init__(
        self,
        manager: "JobManager",
        job_id: str,
        handler_type: str,
        params: dict[str, Any],
        checkpoint: dict[str, Any],
        secrets: dict[str, str] | None = None,
    ) -> None:
        self.manager = manager
        self.ctx = manager.ctx
        self.job_id = job_id
        self.type = handler_type
        self.params = params
        self.checkpoint = checkpoint
        self.secrets = secrets or {}
        self.cancel_event = asyncio.Event()
        self._last_progress_emit = 0.0
        self._state = "running"

    def save_checkpoint(self, data: dict[str, Any]) -> None:
        self.checkpoint = data
        self.ctx.jobs.update(self.job_id, checkpoint=data)

    def state(self, state: str, **extra: Any) -> None:
        self._state = state
        self.ctx.jobs.update(self.job_id, state=state)
        self.manager.emit(
            "job.state",
            {"jobId": self.job_id, "state": state, **extra},
        )

    def progress(
        self,
        stage: str,
        fraction: float,
        message: str,
        *,
        eta_seconds: float | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress_emit < 0.15 and fraction < 1.0:
            return
        self._last_progress_emit = now
        payload = {
            "jobId": self.job_id,
            "stage": stage,
            "fraction": max(0.0, min(1.0, float(fraction))),
            "message": message,
            "at": time.time(),
        }
        if eta_seconds is not None:
            payload["etaSeconds"] = round(eta_seconds, 1)
        self.ctx.jobs.update(
            self.job_id,
            state="running" if self._state != "waiting_rate_limit" else None,
            stage=stage,
            progress=payload,
        )
        self.manager.emit("job.progress", payload)

    def log(self, level: str, message: str) -> None:
        from ..common.logging import redact_text

        safe = redact_text(message)
        self.ctx.jobs.add_event(self.job_id, level, safe)
        self.manager.emit("job.log", {"jobId": self.job_id, "level": level, "message": safe})

    async def wait(self, seconds: float, reason: str) -> None:
        seconds = max(0.0, float(seconds))
        resume_at = time.time() + seconds
        self.state("waiting_rate_limit", resumeAt=resume_at, reason=reason)
        self.progress("waiting", 0.5, reason, eta_seconds=seconds, force=True)
        remaining = seconds
        while remaining > 0:
            step = min(remaining, 5.0)
            try:
                await asyncio.wait_for(self.cancel_event.wait(), timeout=step)
                raise CancelledError()
            except asyncio.TimeoutError:
                remaining -= step
                if remaining > 0:
                    self.progress("waiting", 0.5, reason, eta_seconds=remaining, force=True)
        self.state("running")


class JobManager:
    def __init__(self, ctx: AppContext, emit: Callable[[str, dict[str, Any]], None]) -> None:
        self.ctx = ctx
        self.emit = emit
        self.handlers: dict[str, JobHandler] = {}
        self.tasks: dict[str, asyncio.Task] = {}
        self.contexts: dict[str, JobContext] = {}
        self._heavy = asyncio.Semaphore(1)

    def register(self, job_type: str, handler: JobHandler) -> None:
        self.handlers[job_type] = handler

    async def start(
        self,
        job_type: str,
        params: dict[str, Any],
        project_id: str | None,
        secrets: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if job_type not in self.handlers:
            raise EngineError("JOB_TYPE_UNKNOWN", "This operation is not available.")
        job_id = self.ctx.db.new_id()
        self.ctx.jobs.create(job_id, job_type, params, project_id)
        self.emit("job.state", {"jobId": job_id, "state": "queued", "type": job_type})
        task = asyncio.create_task(self._run(job_id, job_type, params, {}, secrets))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(job_id, None))
        return {"jobId": job_id, "state": "queued", "type": job_type}

    async def resume(self, job_id: str, secrets: dict[str, str] | None = None) -> dict[str, Any]:
        job = self.ctx.jobs.get(job_id)
        if not job:
            raise EngineError("JOB_NOT_FOUND", "That job does not exist.")
        if job["state"] not in ("interrupted", "failed", "waiting_rate_limit", "cancelled"):
            raise EngineError("JOB_NOT_RESUMABLE", "This job is still running or already finished.")
        if job["type"] not in self.handlers:
            raise EngineError("JOB_TYPE_UNKNOWN", "This job cannot be resumed by this build.")
        self.ctx.jobs.update(job_id, state="queued", error=None)
        self.emit("job.state", {"jobId": job_id, "state": "queued", "type": job["type"]})
        task = asyncio.create_task(self._run(job_id, job["type"], job["params"], job["checkpoint"], secrets))
        self.tasks[job_id] = task
        task.add_done_callback(lambda _t: self.tasks.pop(job_id, None))
        return {"jobId": job_id, "state": "queued"}

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self.ctx.jobs.get(job_id)
        if not job:
            raise EngineError("JOB_NOT_FOUND", "That job does not exist.")
        context = self.contexts.get(job_id)
        if context:
            context.cancel_event.set()
            self.ctx.jobs.update(job_id, state="cancelling")
            self.emit("job.state", {"jobId": job_id, "state": "cancelling"})
            task = self.tasks.get(job_id)
            if task:
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=15)
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass
        else:
            self.ctx.jobs.update(job_id, state="cancelled")
            self.emit("job.state", {"jobId": job_id, "state": "cancelled"})
        shutil.rmtree(self.ctx.paths.tmp / job_id, ignore_errors=True)
        return {"jobId": job_id, "state": "cancelled"}

    async def _run(
        self,
        job_id: str,
        job_type: str,
        params: dict[str, Any],
        checkpoint: dict[str, Any],
        secrets: dict[str, str] | None = None,
    ) -> None:
        context = JobContext(self, job_id, job_type, params, checkpoint, secrets)
        self.contexts[job_id] = context
        handler = self.handlers[job_type]
        heavy = job_type in ("analysis", "render", "transcription")
        if heavy:
            await self._heavy.acquire()
        try:
            if context.cancel_event.is_set():
                raise CancelledError()
            context.state("running")
            attempt = 0
            while True:
                try:
                    result = await handler(context, params)
                    break
                except RateLimited as exc:
                    attempt += 1
                    if attempt > 8:
                        raise
                    await context.wait(exc.retry_after_s, exc.message)
                    continue
            context.state("succeeded")
            context.progress("done", 1.0, "Finished.", force=True)
            self.ctx.jobs.update(job_id, state="succeeded", progress={"stage": "done", "fraction": 1.0, "message": "Finished.", "jobId": job_id})
            self.emit("job.result", {"jobId": job_id, "result": result})
            shutil.rmtree(self.ctx.paths.tmp / job_id, ignore_errors=True)
        except CancelledError:
            self.ctx.jobs.update(job_id, state="cancelled")
            self.emit("job.state", {"jobId": job_id, "state": "cancelled"})
            self.emit("job.result", {"jobId": job_id, "error": {"code": "JOB_CANCELLED", "message": "Cancelled."}})
            shutil.rmtree(self.ctx.paths.tmp / job_id, ignore_errors=True)
        except EngineError as exc:
            state = "interrupted" if exc.retryable else "failed"
            self.ctx.jobs.update(job_id, state=state, error=exc.to_dict())
            self.emit("job.state", {"jobId": job_id, "state": state, "error": exc.to_dict()})
            self.emit("job.result", {"jobId": job_id, "error": exc.to_dict()})
            context.log("error", exc.message)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            error = EngineError(
                "JOB_FAILED",
                "This operation stopped unexpectedly. Details are in the log.",
                details={"error": str(exc)[:500]},
            )
            self.ctx.jobs.update(job_id, state="failed", error=error.to_dict())
            self.emit("job.state", {"jobId": job_id, "state": "failed", "error": error.to_dict()})
            self.emit("job.result", {"jobId": job_id, "error": error.to_dict()})
            context.log("error", f"{type(exc).__name__}: {exc}")
        finally:
            if heavy:
                self._heavy.release()
            self.contexts.pop(job_id, None)
