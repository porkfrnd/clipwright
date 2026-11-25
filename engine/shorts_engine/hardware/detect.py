from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..common.paths import AppPaths
from ..common.proc import ProcessRunner
from ..ingest.binaries import BinaryPaths
from ..render.encoder import EncoderProbe


def _ram_bytes() -> int | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullTotalPhys)
        if sys.platform == "darwin":
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True, timeout=5)
            return int(out.strip())
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except Exception:
        return None
    return None


def _cpu_model() -> str | None:
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/cpuinfo") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
        if sys.platform == "darwin":
            return subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=5).strip()
        return platform.processor() or None
    except Exception:
        return platform.processor() or None


class HardwareDetector:
    def __init__(self, paths: AppPaths, bins: BinaryPaths, runner: ProcessRunner) -> None:
        self.paths = paths
        self.bins = bins
        self.runner = runner
        self.encoders = EncoderProbe(bins, runner)

    async def detect(self) -> dict[str, Any]:
        cores = os.cpu_count() or 1
        ram = _ram_bytes()
        try:
            disk = shutil.disk_usage(self.paths.data_dir).free
        except OSError:
            disk = 0
        encoders = await self.encoders.available()
        gpus = await self._nvidia()
        cuda = False
        try:
            import ctranslate2

            cuda = bool(ctranslate2.get_cuda_device_count() > 0)
        except Exception:
            cuda = False
        profile = self._recommend(cores, ram, bool(gpus and any(g.get("cuda") for g in gpus)))
        usable_encoder = next((e for e in encoders if e["ok"]), None)
        return {
            "os": platform.system(),
            "arch": platform.machine(),
            "cpuModel": _cpu_model(),
            "cores": cores,
            "ramBytes": ram,
            "freeDiskBytes": disk,
            "gpus": gpus,
            "cudaUsable": cuda,
            "hardwareEncoders": [
                {"name": e["name"], "ok": e["ok"], "note": e["note"]} for e in encoders
            ],
            "usableHardwareEncoder": usable_encoder["name"] if usable_encoder else None,
            "recommendedProfile": profile,
            "profiles": PROFILES,
            "dataDir": str(self.paths.data_dir),
        }

    async def _nvidia(self) -> list[dict[str, Any]]:
        exe = shutil.which("nvidia-smi")
        if not exe:
            return []
        try:
            result = await self.runner.run(
                [exe, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                timeout=15,
            )
            if result.returncode != 0:
                return []
            gpus = []
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if parts and parts[0]:
                    gpus.append(
                        {
                            "name": parts[0],
                            "memoryMb": int(float(parts[1])) if len(parts) > 1 and parts[1] else None,
                            "driver": parts[2] if len(parts) > 2 else None,
                            "cuda": True,
                        }
                    )
            return gpus
        except Exception:
            return []

    def _recommend(self, cores: int, ram: int | None, has_cuda: bool) -> str:
        ram_gb = (ram or 0) / (1024**3)
        if has_cuda or (cores >= 12 and ram_gb >= 24):
            return "performance"
        if cores >= 6 and ram_gb >= 12:
            return "balanced"
        return "low"


PROFILES = [
    {
        "id": "low",
        "name": "Low-resource",
        "summary": "Best for small laptops and older desktops.",
        "details": [
            "Cloud transcription is recommended for speed; audio chunks leave this computer.",
            "Or use the local Small model at int8, which is slower but private.",
            "One render at a time, software H.264, lower face-sampling rate.",
        ],
    },
    {
        "id": "balanced",
        "name": "Balanced",
        "summary": "A modern laptop or desktop with 6+ cores and 12 GB+ RAM.",
        "details": [
            "Local Small or Medium Whisper at int8 is practical.",
            "Hardware encoding when a test encode succeeds.",
            "Moderate analysis windows and face sampling.",
        ],
    },
    {
        "id": "performance",
        "name": "Performance",
        "summary": "Dedicated GPU or a large CPU with plenty of RAM.",
        "details": [
            "GPU Whisper with the optional acceleration pack (CUDA 12 + cuDNN 9).",
            "Hardware H.264 encoding, larger local models.",
            "Higher face-sampling rate if face tracking is enabled.",
        ],
    },
]
