from __future__ import annotations

import asyncio
import hashlib
import shutil
from pathlib import Path
from typing import Any, Callable


from ..common.errors import EngineError
from ..storage.db import now
from ..storage.repos import ModelRepo
from .catalog import FACE_MODELS, LLM_MODELS, WHISPER_MODELS, face_catalog, llm_catalog, whisper_catalog


def _aggregate_sha(root: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    total = 0
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode())
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(1024 * 1024)
                if not chunk:
                    break
                h.update(chunk)
                total += len(chunk)
    return h.hexdigest(), total


class ModelManager:
    def __init__(self, models_dir: Path, repo: ModelRepo) -> None:
        self.models_dir = models_dir
        self.repo = repo
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> dict[str, Any]:
        installed = self.repo.list()
        by_name = {(m["kind"], m["name"]): m for m in installed}
        items = []
        for entry in whisper_catalog() + llm_catalog() + face_catalog():
            inst = by_name.get((entry["kind"], entry["name"]))
            item = dict(entry)
            item["id"] = inst["id"] if inst else None
            item["installed"] = bool(inst)
            item["path"] = inst["path"] if inst else None
            item["bytes"] = inst["bytes"] if inst else None
            item["installedAt"] = inst["installedAt"] if inst else None
            items.append(item)
        return {
            "items": items,
            "diskUsageBytes": sum((m.get("bytes") or 0) for m in installed),
            "modelsDir": str(self.models_dir),
        }

    def path_for(self, kind: str, name: str) -> Path | None:
        found = self.repo.find(kind, name)
        if not found:
            return None
        path = Path(found["path"])
        return path if path.exists() else None

    def llm_path(self, name: str) -> Path | None:
        """Return the GGUF file for an installed local LLM, if it is present."""
        root = self.path_for("llm", name)
        if not root:
            return None
        files = sorted(root.glob("*.gguf"))
        return files[0] if files else None

    async def download(
        self,
        kind: str,
        name: str,
        *,
        progress: Callable[[float, str], None] | None = None,
        cancel: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        target = self.models_dir / kind / name
        if self.path_for(kind, name):
            existing = self.repo.find(kind, name)
            return existing or {}
        target.mkdir(parents=True, exist_ok=True)
        import httpx

        if kind == "whisper":
            spec = next((m for m in WHISPER_MODELS if m["name"] == name), None)
            if not spec:
                raise EngineError("MODEL_UNKNOWN", f"Unknown Whisper model '{name}'.")
            try:
                from huggingface_hub import snapshot_download
            except ImportError as exc:
                raise EngineError(
                    "MODEL_DOWNLOAD_UNAVAILABLE",
                    "The model downloader is missing from this build. Reinstall the app.",
                ) from exc
            if progress:
                progress(0.02, f"Contacting the model host for {spec['label']}…")
            try:
                await asyncio.to_thread(
                    snapshot_download,
                    repo_id=spec["repo"],
                    revision=spec["revision"],
                    local_dir=str(target),
                    allow_patterns=["*.bin", "*.json", "*.txt", "*.model", "vocabulary.*", "*.md"],
                )
            except Exception as exc:  # network/hub errors are not EngineError
                raise EngineError(
                    "MODEL_DOWNLOAD_FAILED",
                    "The Whisper model could not be downloaded. Check your connection and try again.",
                    details={"error": str(exc)[:500]},
                    retryable=True,
                ) from exc
        elif kind in ("face", "llm"):
            spec = next((m for m in (FACE_MODELS if kind == "face" else LLM_MODELS) if m["name"] == name), None)
            if not spec:
                raise EngineError("MODEL_UNKNOWN", f"Unknown {kind} model '{name}'.")
            filename = spec.get("filename") or Path(spec["url"]).name
            out = target / filename
            tmp = out.with_suffix(out.suffix + ".part")
            label = spec.get("label") or filename
            try:
                # Large local LLMs need a long read timeout; the download is
                # streamed so a slow connection still shows progress.
                timeout = httpx.Timeout(60.0, read=300.0, write=60.0, pool=60.0)
                async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
                    async with client.stream("GET", spec["url"]) as response:
                        response.raise_for_status()
                        total = int(response.headers.get("content-length") or spec["bytes"])
                        done = 0
                        with tmp.open("wb") as fh:
                            async for chunk in response.aiter_bytes(1024 * 1024):
                                if cancel and cancel.is_set():
                                    raise EngineError("JOB_CANCELLED", "Cancelled.")
                                fh.write(chunk)
                                done += len(chunk)
                                if progress:
                                    progress(
                                        0.05 + 0.9 * min(1.0, done / max(total, 1)),
                                        f"Downloading {label}…",
                                    )
            except EngineError:
                tmp.unlink(missing_ok=True)
                raise
            except Exception as exc:
                tmp.unlink(missing_ok=True)
                raise EngineError(
                    "MODEL_DOWNLOAD_FAILED",
                    f"{label} could not be downloaded. Check your connection and try again.",
                    details={"error": str(exc)[:400]},
                    retryable=True,
                ) from exc
            expected_bytes = int(spec.get("bytes") or 0)
            if expected_bytes and tmp.stat().st_size != expected_bytes:
                tmp.unlink(missing_ok=True)
                raise EngineError("MODEL_VERIFY_FAILED", f"{label} download was incomplete or altered.")
            expected_sha = spec.get("sha256")
            if expected_sha:
                sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
                if sha != expected_sha:
                    tmp.unlink(missing_ok=True)
                    raise EngineError("MODEL_VERIFY_FAILED", f"{label} failed its checksum and was rejected.")
            tmp.replace(out)
        else:
            raise EngineError("MODEL_UNKNOWN", "Unknown model kind.")

        if progress:
            progress(0.96, "Verifying model files…")
        sha, total_bytes = await asyncio.to_thread(_aggregate_sha, target)
        record = self.repo.upsert(
            kind,
            name,
            str(target),
            version=(spec.get("revision") or spec.get("sha256") or "")[:12],
            sha256=sha,
            bytes_=total_bytes,
            meta={"catalog": spec},
        )
        if progress:
            progress(1.0, "Model installed.")
        return record

    async def verify(self, model_id: str) -> dict[str, Any]:
        rec = self.repo.get(model_id)
        if not rec:
            raise EngineError("MODEL_NOT_FOUND", "That model is not installed.")
        root = Path(rec["path"])
        if not root.exists():
            return {"ok": False, "reason": "Files are missing."}
        sha, total = await asyncio.to_thread(_aggregate_sha, root)
        ok = sha == rec["sha256"]
        return {"ok": ok, "sha256": sha, "expected": rec["sha256"], "bytes": total, "installedAt": rec["installedAt"]}

    async def delete(self, model_id: str) -> None:
        rec = self.repo.get(model_id)
        if not rec:
            return
        root = Path(rec["path"])
        models_root = (self.models_dir / rec["kind"]).resolve()
        try:
            resolved = root.resolve()
            if resolved == models_root or models_root in resolved.parents:
                await asyncio.to_thread(shutil.rmtree, resolved, True)
        except OSError:
            pass
        self.repo.delete(model_id)

    def record_for(self, kind: str, name: str) -> dict[str, Any] | None:
        return self.repo.find(kind, name)
