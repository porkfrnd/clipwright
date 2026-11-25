# Release

## Public release

[v0.2.0 on GitHub](https://github.com/porkfrnd/clipwright/releases/tag/v0.2.0)

## Artifacts (this build)

Built on 2026-11-25 with Electron 45.4.1, electron-builder 26.18.0, PyInstaller on Python
3.12.12, bundled FFmpeg 7.0.2, yt-dlp 2026.10.26 and Deno 2.9.8.

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| `release/Clipwright-0.2.0-x86_64.AppImage` | 482 MiB | `331a93436f88305fe0854a46f7aea1fab633615c4bb0f6aafc6623580e428702` |
| `release/Clipwright-0.2.0-amd64.deb` | 391 MiB | `9e5d8fc08b5c30c92f2e40d54a26a85b92089c822b019561e9d337b11d1dda10` |
| `release/linux-unpacked/` | 1.3 GiB | directory |

Breakdown of the unpacked app:

| Part | Size |
| --- | --- |
| Frozen engine (`resources/engine`, onedir) | 682 MB |
| Bundled binaries (`resources/resources/bin`) | 284 MB |
| Renderer/main bundle (`app.asar`) | 11 MB |

The AppImage/deb contain Electron + the CPU engine + FFmpeg/ffprobe + yt-dlp + Deno + fonts +
the `llama-cpp-python` runtime used by local AI. Whisper models, the Qwen3 0.6B GGUF, the
YuNet model and a CUDA pack are **not** bundled; they download on demand into the user data
directory with size shown before download. The local AI runtime is ~30 MB; the model is
610 MiB and explicitly opt-in.

## Build from source

Prerequisites: Linux x64, Node ≥ 22, Python ≥ 3.11 (3.12 recommended), network for the first
dependency/binary fetch, a C/C++ toolchain for `llama-cpp-python` when no wheel is available,
and a working display for the UI tests.

```bash
# 1. Python engine
python3.12 -m venv .venv
.venv/bin/pip install -e "engine[dev]"
.venv/bin/pip install pyinstaller pillow

# 2. Desktop dependencies
cd apps/desktop
npm ci

# 3. Pinned external binaries (verifies manifest SHA-256)
cd ../..
./scripts/fetch-binaries

# 4. Generated brand/schemas
./scripts/gen-brand
./scripts/gen-schemas

# 5. Tests and builds
cd engine && ../.venv/bin/python -m pytest -q && cd ..
./scripts/build-engine
cd apps/desktop
npm run typecheck
npm test
npm run dist:linux
```

`npm run dist:linux` writes AppImage, `.deb` and `linux-unpacked/` under
`apps/desktop/release/`. `scripts/verify-package` checks the packaged binaries with an empty
`PATH`, runs the frozen engine handshake and reports sizes.

The engine can be used without Electron:

```bash
.venv/bin/python -m shorts_engine --stdio       # NDJSON protocol
.venv/bin/python -m shorts_engine run-job transcription --params '{...}' --data-dir /tmp/cw
```

## Run

```bash
chmod +x Clipwright-0.2.0-x86_64.AppImage
./Clipwright-0.2.0-x86_64.AppImage

# or
sudo apt install ./Clipwright-0.2.0-amd64.deb
clipwright
```

Data (SQLite, models, assets, outputs, logs) lives in
`~/.config/Clipwright/engine` by default, under the Electron user-data directory used by the
packaged app. It is outside the install directory. The output folder is configurable.

## Runtime troubleshooting

- **AppImage FUSE error:** run with `APPIMAGE_EXTRACT_AND_RUN=1`, install the `.deb`, or use
  `linux-unpacked/clipwright`. The AppImage runtime, not the app, needs FUSE.
- **Engine failed to start:** press **Restart engine** on the screen; inspect
  `~/.config/Clipwright/logs/main.log` and `engine-stderr.log`. The boot screen shows the log
  tail. The supervisor resets its restart budget on a manual restart.
- **URL preview failure:** Clipwright caches previews, retries with fresh extraction and
  alternate YouTube clients, and prefers system FFmpeg for network downloads. For videos that
  require sign-in, use **Settings → Downloads → YouTube cookies**. Otherwise update the
  downloader or import the file locally.

## Clean-machine evidence

- The **unpacked packaged app** completed the full Playwright flow with `PATH=/tmp/emptybin`:
  wizard → local import → real tiny Whisper transcription → stub provider → analysis →
  selection → boundary edit/undo → Studio → real FFmpeg export → validation and security
  assertions. It passed in 54.0 seconds. No system Python, Node, FFmpeg or yt-dlp was on
  `PATH`.
- `scripts/verify-package` launched the bundled FFmpeg/ffprobe/yt-dlp/Deno with an empty
  `PATH` and completed the frozen-engine `hello`/`ping`/`binaries.status` handshake.
- The packaged app was launched by Playwright with an isolated user-data directory;
  `binaries.status` reported the bundled tools and `hardware.detect` reported the expected
  low-resource profile.
- The AppImage itself was started with `APPIMAGE_EXTRACT_AND_RUN=1` and stayed alive for the
  15 s probe. Playwright cannot attach through the AppImage extraction wrapper in this
  environment, so the full UI flow was run against the identical `linux-unpacked` payload.
- **Windows and macOS were not built or tested here.** Linux-specific clean-install evidence
  is strong; Windows requires its own VM/build/signing pass.

## Signing and distribution

- **Linux**: AppImage can be signed with a GPG key and the `.deb` can be signed with
  `debsign`. No signing key is configured in this build; unsigned artifacts trigger the
  usual OS/desktop warnings.
- **Windows**: code signing requires an Authenticode certificate. `electron-builder` NSIS
  config exists, but no Windows artifact was produced or signed.
- **macOS**: out of scope. No signing/notarization.
- **Updates**: the app checks the public GitHub Releases API and links to the notes and
  platform asset. It is notify-only: no auto-download or auto-install. `electron-updater` has
  no publish provider in this build; yt-dlp has its own checksum-verified update action.
  Never enable silent updates without a visible setting and a signed feed.

## Licenses and FFmpeg GPL

Clipwright is MIT (`LICENSE`). The bundled FFmpeg is a **GPL-2.0-or-later** static build with
libx264/libass and is invoked as a separate process. `THIRD_PARTY_LICENSES.md` is generated by
`scripts/licenses` and lists:

- FFmpeg/ffprobe, yt-dlp, Deno, Electron/Chromium/Node,
- bundled OFL fonts and their license texts,
- Whisper and YuNet model licenses and pinned revisions,
- every npm package in the lockfile and every installed Python distribution.

Before commercial redistribution: perform a legal review of GPL compliance, provide the
corresponding FFmpeg source offer, verify the licenses of frozen Python wheels, and keep all
license texts with the installer. `scripts/licenses` is an inventory, not legal advice.

## Release checklist

- [x] Engine unit + integration suite passes (111 passed, 1 skipped).
- [x] Desktop typecheck and Vitest pass (33 tests).
- [x] Playwright dev suite passes (4 tests): long local flow, URL import/download/transcribe,
  cloud rate-limit wait, and update checker states.
- [x] Packaged unpacked app passes the long local flow with an empty `PATH` (54.0 s).
- [x] Subtitle timing integration test burns ASS at source 0 s and 2 s and requires the first
  caption frame within one 30 fps frame.
- [x] Caption Sync Assistant estimates a synthetic ±60/±120/±180 ms shift within 20 ms and
  refuses sparse evidence; 6 s preview uses the export ASS path.
- [x] Tightener dry-run computes keep ranges and planned duration; render removes pauses and
  standalone fillers with 30 ms audio fades and no video transition.
- [x] Provider comparison runs two read-only passes with `persist=False`; Playwright drives the
  modal and confirms two result columns and the recommendation.
- [x] TikTok/Reels/Shorts safe-zone overlays render as guides only, with no export changes.
- [x] URL import test serves real media over HTTP, downloads with bundled yt-dlp (including the
  muxed-stream fallback), and obtains a local Whisper transcript.
- [x] Frozen engine URL metadata import against a real YouTube URL.
- [x] Packaged URL preview (H.264 640×360) after the FFmpeg/network fix.
- [x] Packaged URL preview cache hit and real 1080×1920 URL render with burned-in subtitles.
- [x] Studio subtitle overlay at the first frame of a URL clip (absolute/relative clock fixed).
- [x] Existing YouTube captions imported when available; partial caption downloads survive a second-language 429.
- [x] Compare modal loads distinct, correctly offset previews for both URL candidates.
- [x] Packaged Settings `binaries.status` ~80 ms (bundled version read from MANIFEST).
- [x] Local-LLM install auto-activates the keyless local provider; Settings shows it with no Key button.
- [x] Adjacent transcript windows are batched (default 2) with overlap de-duplication; provider token headers are not double-counted.
- [x] Model Manager **Verify** on the real installed tiny Whisper model succeeds (installed model IDs exposed in `models.list`); regression covered by packaged Playwright.
- [x] Studio subtitle overlay is inside the 9:16 frame and paints above the blur foreground.
- [x] Burned ASS captions wrap into at most two 24-character rows; no text outside the video frame.
- [x] Engine-failure boot screen recovers via Restart engine; renderer reload during an engine restart clears automatically.
- [x] Frozen engine `run-job transcription` and `run-job render` smoke tests.
- [x] Frozen engine local Qwen3 0.6B loaded and answered a JSON probe in 3.6–6.7 s; real metadata generation produced schema-valid output.
- [x] Real local `find_moments` returned a schema-valid candidate after segment-ID normalization (88.5 s / 1,547 tokens on CPU).
- [x] Model Manager lists the Qwen GGUF and its streaming SHA-256 download path is exercised with a local HTTP fixture; **Use for AI** creates a keyless local provider and makes it default. The real 610 MiB GGUF was loaded from a local copy, not downloaded through the UI.
- [x] `scripts/verify-package` passes.
- [x] `scripts/benchmark` writes measured numbers to `docs/BENCHMARKS.md`.
- [x] Update checker passes available/current/error states against a local GitHub API stub; the
  packaged 0.2.0 build reports the public release as current once v0.2.0 is published.
- [x] Cloud transcription resolves a camelCase provider profile and surfaces a 429 as a
  checkpointed wait with a live countdown; covered by `tests/rate-limit.spec.ts`.
- [x] Screenshot set re-captured from real Electron windows, all themes/states.
- [x] `THIRD_PARTY_LICENSES.md` generated and `LICENSE` present.
- [ ] Live Groq AI tests (blocked: no key).
- [ ] Windows build + clean Windows VM test (blocked: no Windows host).
- [ ] Code signing / notarization (requires certificates).
- [ ] Human legal review of GPL redistribution.
