from pathlib import Path

from shorts_engine.api.context import build_context
from shorts_engine.common.paths import AppPaths


def test_prepared_audio_is_reused_only_for_matching_source(tmp_path: Path):
    ctx = build_context(AppPaths(tmp_path / "engine"))
    project = ctx.projects.create("audio test")
    source = ctx.sources.create(
        project["id"], kind="file", local_path="/tmp/video.mp4", content_hash="hash-a", title="Video"
    )
    audio_dir = ctx.paths.assets / source["id"]
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio = audio_dir / "speech.wav"
    audio.write_bytes(b"RIFF-fake")
    ctx.assets.add(
        source["id"], "audio", str(audio), meta={"purpose": "transcription", "sourceHash": "hash-a"}
    )
    assert ctx.transcription.prepared_audio(source, "local_whisper") == audio
    assert ctx.transcription.prepared_audio(source, "cloud_openai") is None
    assert ctx.transcription.prepared_audio({**source, "contentHash": "hash-b"}, "local_whisper") is None
    ctx.db.close()
