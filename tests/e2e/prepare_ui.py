"""Prepare an isolated engine data directory for the Electron Playwright flow.

The real tiny Whisper model is reused if it is already downloaded. The wizard is
deliberately left incomplete so the UI test walks it for real.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shorts_engine.api.context import build_context  # noqa: E402
from shorts_engine.common.paths import AppPaths  # noqa: E402
from shorts_engine.models.manager import _aggregate_sha  # noqa: E402

MODEL_SOURCES = [
    Path("/tmp/cwtrans/models/whisper/tiny"),
    Path.home() / ".config/Clipwright/engine/models/whisper/tiny",
    Path.home() / ".local/share/clipwright/models/whisper/tiny",
]


def main(data_dir: Path, output_dir: Path) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    ctx = build_context(AppPaths(data_dir))
    ctx.settings.set(
        "transcription",
        {
            "engine": "local_whisper",
            "localModel": "tiny",
            "cloudModel": "whisper-large-v3-turbo",
            "providerProfileId": "groq-default",
            "preferCaptions": True,
            "language": "en",
        },
    )
    ctx.settings.set("render", {"outputDir": str(output_dir), "quality": "standard", "preferHardware": False})
    ctx.settings.set("wizard", {"completed": False})
    source = next((p for p in MODEL_SOURCES if (p / "model.bin").exists()), None)
    if source:
        target = ctx.paths.models / "whisper" / "tiny"
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copytree(source, target)
        digest, total = _aggregate_sha(target)
        ctx.model_repo.upsert(
            "whisper",
            "tiny",
            str(target),
            version="test",
            sha256=digest,
            bytes_=total,
            meta={"catalog": {"name": "tiny"}},
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"prepared {data_dir} (model={'yes' if source else 'no'})")
    ctx.db.close()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
