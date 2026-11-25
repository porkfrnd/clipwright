from __future__ import annotations

import os
import sys
from pathlib import Path

from .brand import PRODUCT_NAME


def default_data_dir() -> Path:
    override = os.environ.get("CLIPWRIGHT_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        return base / PRODUCT_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support" / PRODUCT_NAME
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / PRODUCT_NAME.lower()


class AppPaths:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.tmp = self.data_dir / "tmp"
        self.models = self.data_dir / "models"
        self.assets = self.data_dir / "assets"
        self.outputs = self.data_dir / "outputs"
        self.logs = self.data_dir / "logs"
        self.bin = self.data_dir / "bin"
        self.db_path = self.data_dir / "clipwright.sqlite3"
        self.log_path = self.logs / "engine.log"
        for p in (self.data_dir, self.tmp, self.models, self.assets, self.outputs, self.logs, self.bin):
            p.mkdir(parents=True, exist_ok=True)

    def job_tmp(self, job_id: str) -> Path:
        p = self.tmp / job_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def sweep_tmp(self) -> int:
        """Remove leftover temp directories from previous runs."""
        removed = 0
        if not self.tmp.exists():
            return 0
        for child in self.tmp.iterdir():
            if child.is_dir():
                import shutil

                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed
