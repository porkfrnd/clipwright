from __future__ import annotations

import asyncio
import os
import shutil
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import CancelledError, EngineError


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class ProcessRunner:
    """Run child processes with argument arrays, no shell, and killable process groups."""

    def __init__(self) -> None:
        self._children: set[asyncio.subprocess.Process] = set()

    async def run(
        self,
        args: list[str],
        *,
        cancel: asyncio.Event | None = None,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        on_line: Callable[[str], None] | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        if not args or not isinstance(args, list):
            raise ValueError("args must be a non-empty list")
        full_env = os.environ.copy()
        if getattr(sys, "frozen", False):
            # PyInstaller prepends its private library directory to LD_LIBRARY_PATH.
            # External tools (yt-dlp, ffmpeg, deno) must not load the engine's bundled libs.
            original = full_env.get("LD_LIBRARY_PATH_ORIG")
            if original:
                full_env["LD_LIBRARY_PATH"] = original
            else:
                full_env.pop("LD_LIBRARY_PATH", None)
            # These bootloader variables make an unrelated PyInstaller child (yt-dlp)
            # try to reuse this executable's archive. Never leak them to subprocesses.
            for key in list(full_env):
                if key.startswith("_PYI") or key in ("_MEIPASS2", "_PYI_APPLICATION_HOME_DIR"):
                    full_env.pop(key, None)
        if env:
            full_env.update(env)
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=full_env,
            limit=8 * 1024 * 1024,  # yt-dlp emits one JSON line larger than asyncio's 64 KiB default
            **kwargs,
        )
        self._children.add(proc)
        out_chunks: list[str] = []
        err_chunks: list[str] = []

        async def pump(stream, chunks, forward: bool) -> None:
            while True:
                raw = await stream.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", "replace")
                chunks.append(line)
                if forward and on_line:
                    on_line(line.rstrip("\n"))

        tasks = [asyncio.create_task(pump(proc.stdout, out_chunks, False))]
        if on_line:
            tasks.append(asyncio.create_task(pump(proc.stderr, err_chunks, True)))
        else:
            tasks.append(asyncio.create_task(pump(proc.stderr, err_chunks, False)))
        wait_task = asyncio.create_task(proc.wait())
        cancel_task = None
        if cancel is not None:
            cancel_task = asyncio.create_task(cancel.wait())
        try:
            pending = {wait_task}
            if cancel_task:
                pending.add(cancel_task)
            done, _ = await asyncio.wait(
                pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if cancel_task and cancel_task in done and cancel.is_set():
                await self.kill(proc)
                raise CancelledError()
            if wait_task not in done:
                await self.kill(proc)
                raise EngineError(
                    "PROCESS_TIMEOUT",
                    "The media tool took too long and was stopped.",
                    details={"args": [Path(args[0]).name]},
                    retryable=True,
                )
        finally:
            if cancel_task:
                cancel_task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await proc.wait()
            self._children.discard(proc)
        return CommandResult(
            args=args,
            returncode=proc.returncode or 0,
            stdout="".join(out_chunks),
            stderr="".join(err_chunks),
        )

    async def kill(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def kill_all(self) -> None:
        for proc in list(self._children):
            await self.kill(proc)

    async def which(self, name: str) -> str | None:
        return shutil.which(name)
