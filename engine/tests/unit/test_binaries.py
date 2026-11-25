import json
from pathlib import Path

from shorts_engine.api.methods.system import _manifest_version


def test_manifest_version_avoids_starting_ytdlp(tmp_path: Path):
    binary = tmp_path / "bin" / "linux-x64" / "yt-dlp"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"binary")
    (tmp_path / "bin" / "MANIFEST.json").write_text(
        json.dumps(
            {
                "platforms": {
                    "linux-x64": [
                        {"name": "yt-dlp", "version": "2026.10.26"},
                        {"name": "deno", "version": "2.9.8"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert _manifest_version(str(binary), "yt-dlp") == "2026.10.26"
    assert _manifest_version(str(binary), "missing") is None
    assert _manifest_version(None, "yt-dlp") is None
