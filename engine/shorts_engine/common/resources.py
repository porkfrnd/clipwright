from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path | None:
    env = os.environ.get("CLIPWRIGHT_REPO_ROOT")
    if env:
        return Path(env).resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "resources").is_dir() and (parent / "engine").is_dir():
            return parent
    return None


def resources_dir() -> Path | None:
    env = os.environ.get("CLIPWRIGHT_RESOURCES")
    if env:
        p = Path(env)
        return p if p.exists() else None
    root = repo_root()
    if root and (root / "resources").is_dir():
        return root / "resources"
    # Packaged layout: resources sit next to the executable.
    candidate = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "resources"
    return candidate if candidate.exists() else None


def fonts_dir() -> Path | None:
    base = resources_dir()
    if not base:
        return None
    candidate = base / "fonts"
    return candidate if candidate.is_dir() else None


def ass_templates_dir() -> Path | None:
    base = resources_dir()
    if not base:
        return None
    candidate = base / "ass"
    return candidate if candidate.is_dir() else None
