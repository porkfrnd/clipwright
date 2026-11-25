# Fixture attribution

All media fixtures in this directory were generated for Clipwright's automated tests.

| File | Origin | License |
| --- | --- | --- |
| `demo-lecture.mp4` | Generated with FFmpeg from four synthetic `flite` speech segments (`src/s1.wav` … `s4.wav`) and a solid-colour title frame. No third-party footage, music, or voice recording is included. | CC0-1.0 (project-generated) |
| `src/s1.wav` … `src/s4.wav` | Generated with the `flite` speech synthesizer. | CC0-1.0 (project-generated) |
| `stub_server.py` | Project test code; a local OpenAI-compatible stub used only to exercise control flow. | MIT (same as Clipwright) |

These fixtures are intentionally short and synthetic. They are **not** evidence that the app
works on real-world footage or real speakers, and they are not a substitute for the live AI
tests that require a provider API key.
