# Development Log

## 2026-07-12 — Gate 0: Recon

Environment inspected on the build machine:

| Item | Result |
|---|---|
| OS | Debian 13 (kernel 6.12), x86_64 |
| CPU | 4 logical cores, 7.6 GiB RAM |
| Disk | 703 GiB free on the project volume |
| Node | v24.21.0, npm 11.19.0 |
| Python | 3.13.5 system; 3.12.10 and 3.11 available (`~/.local/bin`) |
| FFmpeg | 7.1.5 system build, `--enable-gpl`, has libx264 + libass, loudnorm, sidechaincompress, silencedetect, flite |
| yt-dlp | not on PATH; pip package `yt-dlp 2026.10.26` installs and imports |
| Deno / QuickJS | not installed (needed by current yt-dlp for YouTube challenges; see KNOWN_ISSUES) |
| Python deps | pydantic 2.14.4, httpx 0.28.1, faster-whisper 1.2.1, opencv-python-headless 5.1.0, numpy 2.5.5 all install on Python 3.12 |
| Network | `registry.npmjs.org` 200; `api.groq.com` reachable (401 without key) |
| `GROQ_API_KEY` | **not set** — live Groq tests cannot run in this environment |

Decisions taken from recon:

- Use Python 3.12 for the engine (all native wheels available).
- Bundle binaries are **not** committed; `scripts/fetch-binaries` downloads them at build time. During development the system FFmpeg and the pip `yt-dlp` module are used.
- Because no Groq key is available, the AI pipeline is verified against a **local OpenAI-compatible stub**. This is control-flow evidence only, never evidence that the real Groq endpoint works; live tests are marked NOT RUN and reported as such.

## 2026-11-22 — Implementation log

Work proceeded in small runnable stages. Every command below was run; results are copied from
the terminal, not remembered.

### Foundation, protocol, storage

- Repo layout: `engine/shorts_engine` (Python), `apps/desktop` (Electron main/preload/Svelte
  renderer), `resources` (fonts, icons, pinned binary manifest), `scripts`, `schemas`, `tests`.
- Generated brand and protocol schemas: `scripts/gen-brand` → `brand.generated.ts`;
  `scripts/gen-schemas` → `schemas/protocol.schema.json`, `schemas/methods.json`,
  `schemas.generated.ts`. Generation refuses when the brand mirror is stale.
- Engine migrations create ~25 tables; storage tests cover create/reopen, settings, project
  persistence, candidate revisions/undo and migration columns.
- Protocol tests against a real engine process: handshake, ping, version mismatch, unknown
  method, invalid params, kill/restart. `Request.id` must be a string; test uses `req-N`.

### Ingest, transcription, discovery, render

- Local fixture: `tests/fixtures/demo-lecture.mp4` (48 s, 1280×720, four synthetic `flite`
  speech segments), generated for tests; see `tests/fixtures/ATTRIBUTION.md`.
- Real local Whisper `tiny` download (78 MB), verification and transcription. PyAV decode was
  unreliable, so audio is decoded with FFmpeg to 16 kHz mono float32 before faster-whisper.
- Discovery verified with a local OpenAI-compatible stub: rate-limit wait then resume; cancel
  before provider call; segment-ID regex; 15–90 s bounds; `best_overall`; token usage.
- Render verified: 3-clip batch, ffprobe 1080×1920 H.264/AAC, full decode, subtitle pixels in
  the lower third, cancel leaves no `.part`.
- Added `candidates.revisions` / `candidates.undo`, wired to the Studio Undo button and
  Playwright boundary-edit test. Added Compare two moments side by side and live transcript
  highlighting. Added Home/End keyboard seeking to the moment map.

### Desktop, security, UI

- `contextIsolation: true`, `sandbox: true`, `nodeIntegration: false`; trusted sender +
  main-frame checks on every IPC handler; strict CSP; allow-listed methods; `media://` only
  for registered asset IDs.
- Secrets use Electron 45 async safeStorage (`decryptStringAsync` with `shouldReEncrypt`).
  Linux weak-backend path defaults to session-only and requires warned opt-in.
- Native dialog stubs and `files:registerDropped` for deterministic E2E/drag-and-drop.
- Svelte 5 proxies are not structured-cloneable; `lib/api.ts` and preload JSON-round-trip
  every request.
- Fixed Electron startup: `app.setName(PRODUCT_NAME)` then optional
  `CLIPWRIGHT_USER_DATA` path for isolation.
- UI additions: wizard skip-provider and a11y labels; light appearance for non-ivory themes;
  compact density; privacy panel; compare modal; boundary undo; long-title handling.
- Contrast pass found `--faint` below 4.5:1 on surfaces. Adjusted all four themes; measured
  token pairs now: Velvet 4.54, Ember 4.50, Slate 4.84, Ivory 4.68. Body/muted pairs are
  4.63–17.2:1.

### Frozen-engine bug found during release verification

A real URL import through the frozen engine failed with `SOURCE_METADATA_FAILED` while the
same yt-dlp command worked in the shell. Root cause: `ProcessRunner` used asyncio's default
64 KiB stream limit; yt-dlp emits a ~178 KB single JSON line, `readline()` exceeded the limit,
and the pump task failed silently. Fix: set `limit=8 MiB` on `create_subprocess_exec` and added
`engine/tests/unit/test_proc.py` with a 200 KB stdout line. Also stripped PyInstaller
`_PYI_*`/`LD_LIBRARY_PATH` bootloader variables from child processes so the one-file yt-dlp
runtime is not confused by its parent's archive.

After the fix, the frozen engine imported real YouTube metadata:

```text
engine.hello → Clipwright 0.1.0
source.import_url (https://www.youtube.com/watch?v=aqz-KE-bpKQ)
elapsed 31.3 s, no error
title: Big Buck Bunny 60fps 4K - Official Blender Foundation Short Film
channel: Blender · duration 635.0 s · 3840×2160 · kind url
```

### Final test evidence

| Check | Command | Result |
| --- | --- | --- |
| Engine unit + integration | `cd engine && ../.venv/bin/python -m pytest -q` | **67 passed**, 1 Pillow deprecation warning, 99.76 s |
| Engine protocol restart | included above | pass |
| Real local Whisper | included above | pass, `wordTiming: exact`, 3 segments |
| Render batch/cancel/subtitles | included above | pass |
| Frozen transcription | `shorts-engine run-job transcription` | `state: succeeded`, 3 segments, 40.58 s, 21 s wall |
| Frozen render | `shorts-engine run-job render` | 1/1 succeeded, 1080×1920, h264+aac, 817,038 bytes |
| Frozen URL metadata | real YouTube URL, empty-ish PATH | title/channel/duration/4K metadata, 31.3 s |
| Desktop typecheck | `npm run typecheck` | pass |
| Vitest | `npm test` | **9 passed** |
| Playwright dev | `npx playwright test` | **1 passed** (1.3 m), includes URL validation, wizard, local import, real Whisper, provider stub, analysis, boundary save/undo, Studio, real export, security assertions |
| Playwright packaged | `CLIPWRIGHT_E2E_EXECUTABLE=…/release/linux-unpacked/clipwright npx playwright test` | **1 passed** (1.4 m) |
| Playwright packaged, no system tools | same + `CLIPWRIGHT_E2E_EMPTY_PATH=1` (app `PATH=/tmp/emptybin`) | **1 passed** (1.3 m) |
| Package verification | `./scripts/verify-package` | binaries execute with empty PATH; hello/ping/binaries.status ok; sizes reported |
| Benchmark | `./scripts/benchmark` | 13 s speech → 8.7 s (1.49× RT, 447 MB); 15.8 s render → 18.0 s (0.88× RT, 722 MB child RSS) |
| Screenshots | `node tests/screenshots.mjs`, `node tests/ratelimit_shot.mjs` | 20 PNGs in `docs/screenshots/`; rate-limit state from a real 429 stub |

### Packaging evidence

```text
release/Clipwright-0.1.0-x86_64.AppImage   477 MiB  sha256 19c9f512…4652
release/Clipwright-0.1.0-amd64.deb         381 MiB  sha256 bb45b306…da47
release/linux-unpacked                     1.2 GiB
  resources/engine (frozen)                 652 MB
  resources/resources/bin                   283 MB
  app.asar                                  9.5 MB
```

AppImage note: `APPIMAGE_EXTRACT_AND_RUN=1 ./Clipwright-0.1.0-x86_64.AppImage --no-sandbox`
stayed alive for the 15 s probe (timeout 124). Playwright cannot attach through the extraction
wrapper, so the full flow was run against the identical `linux-unpacked` payload.

`scripts/verify-package` output:

```text
ffmpeg version 7.0.2-static
ffprobe version 7.0.2-static
2026.10.26
deno 2.9.8
engine.hello ok
engine.ping ok
binaries.status ok
Package verification complete.
```

### What is NOT verified

- **Live Groq/cloud AI.** `GROQ_API_KEY` is not set. All AI verification used the labeled
  local stub. This is not evidence of real model quality or real endpoint behavior.
- **Live cloud transcription.** No key.
- **Windows build / clean Windows VM.** No Windows host or signing certificate.
- **Hardware encoders.** Test encodes failed on this machine; software only.
- **Face tracking.** Not implemented.
- **URL selective retrieval/render.** Metadata import verified; section fetch/render from a
  URL not exercised.
- **Subtitle frame-accuracy.** Burn-in pixels and full decode verified; A/V offset not
  instrumented.
- **App auto-updates.** No update feed configured.

### Final docs

Wrote `ARCHITECTURE.md`, `PROTOCOL.md`, `DESIGN_SYSTEM.md`, `DECISIONS.md`,
`KNOWN_ISSUES.md`, `RELEASE.md`, README, `LICENSE`, `tests/fixtures/ATTRIBUTION.md`, and a
generated `THIRD_PARTY_LICENSES.md` (`scripts/licenses`, 432 npm packages, 45 Python
distributions). Captured and reviewed 20 screenshots across populated/empty/error/rate-limit/
long-title states, four themes, compact density and small/large windows.

## 2026-11-22 — Post-release incident: engine startup stuck screen

Reported: the packaged AppImage showed “The media engine could not start” and stayed there even
though an engine process was running. The previous session had downloaded `tiny`, transcribed
a real URL source, run analysis and hit 403s on URL preview downloads.

### What was found

1. `EngineClient` had two restart races. `restart()`/`spawnChild()` nulled `this.child` before
   the old process exited; the old child's `exit` handler then rejected the **new** child's
   requests and scheduled another restart. A late `engine.hello` rejection from the old child
   could do the same. This can produce repeated restarts and a permanent-looking failed screen.
2. `ensureBoot()` returned early whenever `appState.booted` was true. `refreshBoot()` sets
   `booted = true` before `App.svelte` sets `shellReady`; any later failure left the boot screen
   permanently stuck.
3. “Try again” only reloaded the renderer and could not reset the supervisor. There was no
   manual engine restart and no main-process log.
4. The bundled johnvansickle **FFmpeg 7.0.2 segfaults on any HTTPS input** (`SIGSEGV`,
   exit 139), so yt-dlp section downloads failed and some URL previews surfaced as 403/ffmpeg
   errors. Local-file FFmpeg work was unaffected.

### Fixes

- Stale child exits are ignored; only the current child may reject requests or schedule a
  restart. Stale `engine.hello` resolutions/rejections are ignored.
- Engine pings are less aggressive: 8 s interval, 6 s timeout, 3 misses (24 s tolerance).
- Added `engine.restart` (main + preload + typed API) with a fresh restart budget, plus
  **Restart engine** buttons on both the boot-failure and fatal recovery screens.
- `ensureBoot` now finishes from already-loaded state instead of returning early; the boot
  screen polls `engine:status` every 2.5 s, retries boot on transient failure, and shows the
  engine log. “Reload window” remains available.
- Main process now writes `logs/main.log` for status/restart/renderer-crash diagnostics; a
  renderer process crash is auto-reloaded at most twice, with a 60 s reset window.
- URL preview prefers **system FFmpeg** for yt-dlp network downloads when present. On a clean
  machine with no system FFmpeg, it downloads a progressive stream with yt-dlp's **native**
  downloader and cuts it locally with the bundled FFmpeg. URL preview format prefers H.264.
- Captured a new AppImage/.deb build after these fixes.

### Recovery tests run

| Scenario | Result |
| --- | --- |
| Start packaged app with engine executable non-executable | Shows failure/recovery screen |
| Restore engine executable, click **Restart engine** | Reaches the setup wizard; no terminal needed |
| Kill the running engine child, reload the renderer immediately | Boot screen clears after automatic restart |
| Kill engine while app is open (dev) | App remains usable, engine returns `ready` |
| Packaged URL preview, real YouTube source | `media://` preview produced; H.264 640×360 + AAC, 17.1 s padded section |
| User profile boot with new package | Home loads; 1 project; no boot error |
| Packaged full local flow, `PATH=/tmp/emptybin` | Passed again (1.5 m) |

### New artifact hashes

```text
AppImage 477 MiB  sha256 19c9f512fc9ef277bb44a436f2dfc3ba19b2ba626eb6ebf71f118a30763f4652
deb      381 MiB  sha256 bb45b30684d75260dc3937c8543af67d9703fda88daf9f65f8746f58e5bada47
```

The old AppImage process was stopped before rebuilding; launch the new artifact at
`apps/desktop/release/Clipwright-0.1.0-x86_64.AppImage`.

## 2026-11-23 — YouTube preview cache, subtitle clock, and retry hardening

Reported after the first packaged run: YouTube imports/previews still hit intermittent 403s,
and subtitles did not appear at first in the Studio/preview path.

### Root causes

1. `AssetRepo.for_source()` returned camelized rows but did **not** parse `meta_json` into
   `meta`. Every preview/render cache lookup therefore missed. Each Studio visit re-downloaded
   the same YouTube section, and each render re-downloaded its source section. That repeated
   traffic made YouTube 403/rate-limit behaviour much more likely.
2. The Studio's subtitle overlay used the wrong clock for URL clips. The downloaded preview is
   a section starting before the candidate, so its `<video>` time is relative; the transcript
   timestamps are absolute. The overlay compared 0–20 s with ~560 s and never found a line.
   Local files also double-added the candidate start. The preview also began several seconds
   before the first word, so even a corrected clock showed nothing until playback advanced.
3. A single failed yt-dlp section request went straight to a full-download fallback. There was
   no fresh-extraction retry and no alternate YouTube client.

### Fixes

- `AssetRepo.for_source()` now exposes parsed `meta` for every list result (same shape as
  `get()`), so previews and render sections cache correctly.
- Preview cache keys include both requested start and end, and return the actual downloaded
  section offset. URL previews now start at the chosen moment, with the pad retained for
  rewinding.
- Studio tracks `previewOffset`; subtitle time is `video.currentTime + previewOffset`. Local
  files use offset 0. Initial paused frame now shows the first caption.
- yt-dlp now retries with fresh extraction, alternate `web_embedded`/`mweb` clients and a
  progressive format before the native full-download fallback. Retry/fragment/extractor
  retries and socket timeout are set.
- Optional **Settings → Downloads → YouTube cookies** uses a Netscape `cookies.txt` for
  sign-in/age-gated videos. It is stored locally, is never sent to an AI provider, and can be
  cleared.
- Added regression tests for asset metadata, the YouTube retry/client ladder and cookies
  forwarding.

### Verification

| Check | Result |
| --- | --- |
| Engine unit/integration suite | **71 passed, 1 skipped** |
| Desktop typecheck / Vitest | Passed; **9 passed** |
| Playwright local flow incl. subtitle overlay | **passed in 53 s** |
| Packaged Playwright flow, `PATH=/tmp/emptybin` | **passed in 1.7 m** |
| Packaged URL preview, real YouTube section | H.264 section; second request `cached: true`, same asset |
| Packaged URL Studio subtitle at first frame | `here and see what these guys are talking` |
| Real URL 1080×1920 render with burned-in words | **succeeded**, 19.97 s, 17,427,162 bytes |
| Local showcase render after fixes | Output validated by ffprobe |

### New artifact hashes

```text
AppImage 477 MiB  sha256 e6071a481bcfa20fcce8ed89e86fc8e152d710ca10a6eb686521ab630d7232f2
deb      381 MiB  sha256 c1407ead6fd7fbefd6020e7e3741b34c53af3dd6e08f87c9779668f87719c040
```

## 2026-11-24 — Subtitle rigor, caption fast path, and interaction cache fixes

Follow-up request: look for more bugs, improve slow paths, and add stronger subtitle tests.

### Bugs fixed

1. **Partial caption downloads were discarded.** yt-dlp can write `en-orig` and then fail on
   the translated `en` with HTTP 429. The old code raised on the non-zero exit and deleted the
   usable file, forcing a 7-minute Whisper run. `download_subtitles()` now returns any valid
   caption file and retries alternate clients if none were written.
2. **Caption language order made 429 more likely.** The job asked for `en,en.*`, so the
   translated `en` could fail before `en-orig`. The request is now `en.*,en` (using the base
   language) and the packaged caption path completed a 626 s source in ~52 s.
3. **Render sections were cached only in the job temp dir and keyed by candidate alone.** The
   second export re-downloaded the section, and a boundary edit could reuse the wrong range.
   Sections are now persisted under assets and keyed by candidate + exact padded range.
4. **Subtitle preview had no phrase-only fallback.** Transcripts without word timings showed
   nothing in Studio even though the render had a caption. `subtitleWords()` now uses segment
   text as one caption word and clips every word to the clip range.
5. **Project URL previews used the wrong local clock.** Preview offsets are tracked, map seeks
   are translated, and the compare modal fetches a distinct, correctly offset section for both
   URL candidates instead of reusing one candidate’s preview.
6. **Studio edit debounce could write to the wrong clip.** The selection id and payload are
   captured before the 320 ms timer; a late result is not applied to a newly selected clip.
7. **Downloader update dropped the cookies setting.** `reload_binaries()` preserves the cookie
   file, and `YtDlp.version()` caches the version probe.
8. **`binaries.status` took ~2.3 s** because it started yt-dlp just to print its version. The
   bundled version is read from `MANIFEST.json`; only user-updated copies run `--version`.
   Settings now sees ~80 ms.
9. **Blur renders did a full-resolution gaussian blur.** The background is blurred at half
   resolution and upscaled, with the same visual result and less filter work.

### Subtitle test coverage

- New pure TS model (`lib/subtitles.ts`) with **12 tests** covering clipping,
  boundary words, phrase-only fallback, wrapping, gaps, lead-in/out, active-word changes,
  relative URL clocks and local absolute clocks (21 desktop tests pass in total).
- New Python tests for ASS clip-relative events, no-invented-text clipping, phrase-only
  captions, partial caption downloads, caption transcript caching, render-section cache and
  boundary invalidation, and manifest version reads.
- Full engine suite: **78 passed, 1 skipped**. Desktop: **21 passed**.

### Interaction verification (packaged build)

| Check | Result |
| --- | --- |
| Packaged local E2E with `PATH=/tmp/emptybin` | passed (1.1 m) |
| Packaged cold start → Home | 1.9 s |
| `binaries.status` | ~80 ms cold, ~28 ms cached |
| Packaged YouTube captions | succeeded; 295 segments, origin `subtitle` |
| Compare modal, two URL candidates | 2 videos, 2 distinct sources, no error box |
| Studio subtitle at first frame | visible |
| URL render / subtitle burn-in | verified earlier; still uses same ASS path |

### Final artifact hashes

```text
AppImage 477 MiB  sha256 eaaabb73a6385fe3a77a7338723462e5450c7d8f9f860cb59cb0f1c7a0c7a58b
deb      381 MiB  sha256 aeb2a033d30c490e463ac192d4e072c9702a943720ff58323dedba1ead0c1bd0
```

## 2026-11-24 — Second optimization pass (measured hot paths)

Profiled the application from a cold launch through Project, Studio, transcript save/read,
local Whisper, URL preview and render. Changes were driven by measurements, not guesses.

### Measurements and changes

| Hot path | Before | After | Change |
| --- | ---: | ---: | --- |
| Synthetic 295-segment / 1,475-word transcript save | 2.105 s | 0.072 s | One transaction + `executemany` |
| Real transcript full read (170 segments / 1,976 words) | ~78 ms first read | ~17 ms warm | One grouped join |
| Project transcript read (no word rows) | ~17 ms | ~1 ms | `includeWords:false` |
| Local Whisper, real 626 s audio | 66.8 s (beam 5) | 40.4 s (beam 1) | Greedy CPU decoding |
| First local transcription end-to-end | ~75 s class | 43.5 s | Beam 1 + bulk save |
| Second local transcription of same source | re-extract + hash | 0.33 s | Prepared audio asset reuse |
| Concurrent identical URL previews | 2 downloads / 2 assets | 1 download / 1 asset | Per-range lock |
| Engine module import (`api.app`) | ~502 ms | ~281 ms | Lazy numpy/httpx/AI engines |
| Engine cold `hello` (source run) | ~649 ms | ~610 ms | Lazy imports |
| Bundled source at ~30 fps | always `fps=30` filter | filter omitted | Less filter work |

Also added migration-2 lookup indexes, batched candidate revisions, single-query Job/Project
lists, ffprobe caching by path/size/mtime, and lazy word loading in Project. `transcript.get`
now accepts `includeWords` (default true) so Studio, render and analysis keep exact words while
Project loads only segment text and timings.

### Verification

- Engine suite: **82 passed, 1 skipped** (new preview single-flight, prepared-audio, lean
  transcript tests).
- Desktop: **21 tests passed**, typecheck clean.
- End-to-end local benchmark used the real user 626 s speech asset and the installed `tiny`
  model: first run 43.48 s / 184 segments / 1,934 words; second run 0.333 s with one cached
  audio asset.
- The final packaged acceptance flow is run after rebuilding the engine and AppImage/deb.


## 2026-11-24 — Subtitle preview layering and frame-size regression

The reported “subtitles go behind the clip / wrong size” was reproducible in Studio’s Blur fit
preview:

- `Player` caps its 9:16 frame at 62vh, so the actual video was 257 px wide while the
  subtitle’s positioned parent stayed 430 px wide. The overlay/text was wider than the video.
- The overlay had `z-index:auto`; in blur layout the foreground tile has `z-index:1`, so the
  text painted behind the clip.
- The preview font size was a fixed 0.42 of 64–70 px instead of being scaled from the actual
  frame width.
- Separately, ASS caption rows allowed ~48 characters on one line while `WrapStyle:2` disables
  libass auto-wrapping, so long captions could run outside the safe area.

### Fix

- Parent preview width is now `min(430px, 34.875vh)`, matching the 62vh 9:16 frame.
- `SubtitlePreview` receives `scale = frameWidth / 1080`, scales font/outline/shadow, and uses
  `z-index:3`.
- ASS rows are capped at `MAX_CHARS_PER_LINE=24`, at most `maxLines` rows per event, joined
  with explicit `\N` while preserving word-highlight events.
- Playwright now asserts the subtitle bounding box stays inside the real frame and hit-tests
  above the foreground video in Blur fit.
- Added Python coverage for explicit caption row wrapping and `\N` events.

### Verification

- Packaged Playwright acceptance: **passed (55.1 s)** with the new layering assertion.
- Real 1080×1920 export frame with the user’s 70 px center caption: two wrapped rows, fully
  inside the frame.
- Desktop: **21 tests passed**; engine: **82 passed, 1 skipped**.
- Final package hashes:

```text
AppImage 477 MiB  sha256 e293a757275ed82624b5f8414a334b89ec202a102c54ac71f029bd6087e41575
deb      381 MiB  sha256 7b9cb22dc1715c5e507a29fd422d6351847d86946eba06a01b74ee9d6235d91e
```

## 2026-11-24 — Optional local AI (Qwen3 0.6B GGUF)

Added a local analysis provider so Clipwright can find moments without a Groq key and without
sending the transcript off the machine.

### What was added

- `LLM_MODELS` catalog entry `qwen3-0.6b`: Qwen3 0.6B instruct, Q8_0 GGUF, 610 MiB, pinned
  Hugging Face revision `23749fef…` and SHA-256 `9465e63a…`, Apache-2.0. (The request said
  “Qwen 0.8B”; Qwen3 0.6B is the smallest Qwen3 instruct release, so that is the model used.)
- Model Manager now lists a **Local AI** section, downloads the GGUF into the user data
  directory, verifies length + SHA-256, and offers **Use for AI** after installation.
- A `local` provider adapter runs the GGUF in-process through `llama-cpp-python`. It has no
  base URL, no key, and no HTTP path. The frozen engine bundles `llama_cpp` and its shared
  libraries; the model itself is never inside the installer.
- Local structured calls append `/no_think` (Qwen3 soft switch), send the Pydantic JSON
  schema in the system prompt, strip fences/prose, validate, and retry once with the
  validation error. Provider Test performs a real tiny JSON generation, not just a file
  check.
- `provider.save` validates `local://<model>` separately from HTTP(S), and `provider.test`
  reports the model as ready without requiring a secret.
- The first request pays model load; the adapter caches the loaded model for the engine
  process. CPU-only is intentional for portability.

### Verification

- Real Q8_0 GGUF loaded and answered a JSON probe in **3.6–6.7 s** through the **frozen engine**
  on this 4-core CPU machine (`provider.test`, packaged engine).
- Source adapter tests: **5 passed** (prompt/schema, `/no_think`, missing-model error,
  catalog pin, local URL validation).
- Full engine suite: **92 passed, 1 skipped**.
- Desktop: **21 tests passed**, typecheck clean.
- Packaged Playwright flow: **1 passed (51.3 s)** with `PATH` empty, including a keyless
  local-provider UI assertion (installed Qwen row → Use for AI → Default AI → Settings has no Key button).
- An actual metadata generation against the local model completed in **24.0 s** and returned
  a schema-valid title, description, hashtags, hooks and thumbnail suggestions. This is a
  smoke test of the runtime/schema path, not evidence of 0.6B analysis quality.
- Local model quality is expected to be below Groq; the UI and docs say so. No Groq key was
  available, so live Groq remains NOT RUN.

### Final artifacts for the local-AI build

```text
AppImage 481 MiB  sha256 b6c39c891f835d426eb62465e75be04b87b5c00230016ab8fed6790269a8b290
deb      390 MiB  sha256 ce22856274616ae88264879ff5fc5750347acb91e46ac6c1152da1211257677b
```

`scripts/verify-package` passed with an empty `PATH`; the packaged Playwright flow passed in
51.3 s. The AppImage/deb now include the `llama-cpp-python` CPU runtime (~30 MB); the Qwen
model remains a 610 MiB opt-in download.

## 2026-11-24 — Model Verify parameter error (user-reported)

**Symptom.** Clicking **Verify** on an installed transcription model showed “invalid parameters”.

**Root cause.** `ModelManager.list()` returned catalog/card fields but not the installed
`model_registry.id`. The Model Manager’s Verify and Remove actions pass `model.id` to
`models.verify` / `models.delete`; with `undefined`, the strict IPC/params validator rejected
the request before the engine could verify anything.

**Fix.** `models.list` now includes `id` for every installed item (`null` when not installed).
Added a unit test for the list shape and a packaged Playwright assertion that clicks **Verify**
on the real installed `tiny` Whisper model, expects the success toast, then verifies the local
Qwen test row as well. `prepare_ui.py` now records the correct tiny model aggregate hash so the
verification is a real hash check, not a mock.

**Verification.** Engine **92 passed, 1 skipped**; desktop **21 passed**; typecheck clean;
packaged Playwright **passed (1.0 min)** with empty `PATH`; `scripts/verify-package` passed.

Final artifacts:

```text
AppImage 481 MiB  sha256 b6c39c891f835d426eb62465e75be04b87b5c00230016ab8fed6790269a8b290
deb      390 MiB  sha256 ce22856274616ae88264879ff5fc5750347acb91e46ac6c1152da1211257677b
```

## 2026-11-24 — Make local AI immediately usable; reduce Groq pressure

### Local AI download → activation

The download button worked, but activation was a separate **Use for AI** action that was easy
to miss. A successful local-LLM download now immediately creates/updates the keyless `local`
provider and makes it the default analysis provider. The row still shows the explicit
**Use for AI / Default AI** state, and Settings shows the provider with a `no key` badge.

The real 610 MiB Qwen3 0.6B GGUF was downloaded through `ModelManager.download` and verified
(639,446,688 bytes; aggregate verification hash recorded). Model Manager’s streaming path
emits many progress updates for a 610 MiB file; the UI remains responsive.

### Rate-limit accounting and batching

Two changes address Groq pressure:

1. **No double-counting.** The adapter previously applied the provider’s authoritative
   `x-ratelimit-*` snapshot and then added the local estimate on top. That made the next
   request think the minute budget was nearly exhausted. Completed requests now record actual
   `usage.total_tokens`; server counters are not double-counted. Request logs show actual
   tokens.
2. **Batched windows.** Adjacent transcript windows are now sent in batches (default 2,
   configurable in **Settings → Clip discovery → Windows per request**). Overlapping transcript
   segments are de-duplicated inside a batch, so the system prompt and overlap are not paid
   twice. A 626 s source with two 360 s windows becomes one map request, not two; the ranking
   request is unchanged. Validation still receives all original segment IDs.

This cannot create more provider quota. If a Groq plan’s TPM is lower than one batch + output,
the UI will still wait/resume; the local provider has no rate limit and is the offline fallback.

### Verification

- Engine **92 passed, 1 skipped**.
- Desktop **21 passed**, typecheck clean.
- Packaged Playwright **passed (57.6 s)** with empty `PATH`.
- Real local GGUF download completed and the file passed the pinned SHA-256 check; adapter
  probe and metadata generation were verified against the real model in the prior local-AI
  pass.
- New tests cover batched-window overlap de-duplication and server-snapshot token accounting.
- Live Groq rate-limit behavior remains **NOT RUN** (no key); no claim is made about a
  specific Groq plan.

Final artifacts:

```text
AppImage 481 MiB  sha256 b6c39c891f835d426eb62465e75be04b87b5c00230016ab8fed6790269a8b290
deb      390 MiB  sha256 ce22856274616ae88264879ff5fc5750347acb91e46ac6c1152da1211257677b
```

### Local discovery smoke test and segment-ID normalization

A real end-to-end local `find_moments` call against the installed Qwen3 0.6B GGUF initially
failed validation because the model copied whole prompt labels (`s0000|00:00:00`) into
`start_seg`/`end_seg`. The adapter now tells the model to return only the ID, and the schema
extracts the unambiguous `sNNNN` prefix before validation. Raw timestamps are still rejected.
After the fix the same real local call returned a valid candidate in **88.5 s / 1,547 tokens**;
this is CPU-only 0.6B behavior and is why the UI labels local AI as slower.

The same installed model was registered in the local user data and a keyless local provider
was made the default, so the app no longer requires a second activation step after download.

Final artifacts for this pass:

```text
AppImage 481 MiB  sha256 b6c39c891f835d426eb62465e75be04b87b5c00230016ab8fed6790269a8b290
deb      390 MiB  sha256 ce22856274616ae88264879ff5fc5750347acb91e46ac6c1152da1211257677b
```

## 2026-11-25 — Release desk, editorial pass, and cloud-path fixes

The interface moved from the earlier poster-like treatment to a quieter editorial "cutting room":
Source Serif 4 display type, Inter for controls, JetBrains Mono for ledger details, warm brass
on graphite, hairline rules, and a four-frame contact strip in the wizard. The boot sheet uses
a film-leader motif instead of a spinner. All screenshots were regenerated from the real app.

**Update desk.** The main process checks the public `porkfrnd/clipwright` release feed once when
the app opens, caches the answer for ten minutes, and exposes it through a narrow preload bridge.
The renderer adds a quiet banner, a nav badge, and an Updates page with release notes, platform
asset choice, and a manual recheck. Failure is silent; the page states what happened without
blocking the rest of the app. Version is 0.1.1.

**Real bugs found while exercising the app.**

- Cloud transcription compared a camelCase provider profile with `base_url`, so every cloud
  transcription failed with "Choose a speech service provider" even when a valid profile was
  selected. The service now accepts `baseUrl` (with the snake-case alias kept for compatibility).
- `CloudTranscriptionEngine` slept through three 429 retries before raising. That delayed the job
  manager's checkpointed wait by up to 90 seconds and hid the countdown. It now raises `RateLimited`
  immediately; the job manager waits, checkpoints, and the UI shows the remaining seconds.
- Blur fit hid its own backdrop: the foreground video painted an opaque black letterbox over the
  blurred copy. The foreground background is now transparent in blur layout.
- At 1120 px the Home action button overlapped the hero copy. The hero is now a two-column grid
  that reserves space for the button, collapsing to one column on phones.
- Wizard "Skip setup" was visually primary despite being a secondary action; it is muted now.

**Verification.** Engine `93 passed, 1 skipped`; desktop `33 passed`; typecheck and production
build clean with no Svelte a11y warnings; Playwright `3 passed` (rate-limit 3.8 s, full local
flow 45.2 s, update checker 4.3 s). The rate-limit test covers the exact cloud transcription
regression above. Screenshots `01`–`16`, `18`–`20` regenerated at 1440×900 (plus the large and
small layout shots); the duplicate fresh-profile wizard shot was removed.


## 2026-11-25 — Clipwright 0.2: subtitle timing, compare, sync, tighten, safe zones

This pass started from a reproduction-first rule: read and record the failure before changing the
renderer or the engine. The following were reproduced in the real app or in a deterministic test.

### Subtitle timing drift (reproduced, then fixed)

**Reproduction.** Render a clip whose selection starts at 2.0 s. burn the ASS into the clip, then
extract the first frame that contains subtitle pixels. The first caption appeared earlier/later
than the source word because the downloaded section started at a keyframe before 2.0 s while the
ASS was built with 2.0 s as time zero. The same drift was visible in Studio preview for URL
sources: the video clock was section-relative, the subtitle clock was source-absolute.

**Root cause.** `yt-dlp --download-sections` cuts at keyframes and may include pre-roll. The
engine assumed the requested start was the container start. Two fixes were needed and both are
kept: `--force-keyframes-at-cuts` for exact cuts, and a fresh probe of the produced container's
`start_time` (`start_time_s`) used as the measured offset. Manifest/cache entries carry the
measured start so the API can build section-relative subtitle events without guessing.

**Regression guard.** `engine/tests/integration/test_subtitle_timing.py` burns captions at
source starts 0 s and 2 s, probes the output, and asserts the first subtitle frame is within one
30 fps frame of the expected time. The Studio header shows "timing at source" or the measured
global shift, so a silent drift is visible without opening the render.

### Caption Sync Assistant (local, conservative)

A local audio-RMS onset check estimates whether every caption is early or late. It looks for a
quiet lookback and a loud lookahead around each word, scores candidate offsets, and returns the
earliest strong plateau rather than the global maximum. This removes the +40–50 ms bias found in
the first version. It never moves spoken audio and never rewrites the transcript: the result is a
global `offsetMs` plus per-line overrides, stored non-destructively in `edit.settings.subtitles`.
When word timings are missing or the score is not high-confidence, the UI refuses to apply an
automatic shift. The 6-second 540×960 preview uses the same ASS builder as the export.

Unit coverage shifts a synthetic click train by ±60/±120/±180 ms and requires the estimate to
land within 20 ms; sparse audio returns "not enough evidence".

### Pause and filler tightener (opt-in, dry-run first)

`plan_timeline` removes interior pauses over a threshold and, optionally, standalone filler
words (`um, uh, erm, hmm, mm, mhm`). It returns keep ranges, removed spans and a planned duration.
The renderer builds a trim/concat video bus and an `atrim`/`afade` audio bus with 30 ms fades at
each cut. This is honest about what it is: cuts with short audio fades, **not** overlapping video
crossfades. Source files, source audio and the transcript are never modified. Studio shows a
review list, before/after duration and the number of pauses/fillers before the user enables it.

### Provider comparison

`analysis.compare` runs two provider/model pairs against the **same cached transcript**, with
`persist=False` in `DiscoveryPipeline`. It writes no run, no candidates and no project state.
The modal shows candidate counts, mean fit, length range, tokens and the per-provider error; its
recommendation is computed from those real results. "Analyze with this one" starts a normal
analysis with the chosen provider, which is the only step that persists candidates. A Playwright
assertion drives the modal through the local stub and verifies the two result columns.

### Safe zones

TikTok, Reels and Shorts overlays are measurement guides only: dashed frames at the documented
top/bottom/right insets, with text labels. They are never burned into the render and never block
pointer input.

### Skip-setup race remounted Home (reproduced by the URL test)

The URL test intermittently lost its open link panel after typing the URL. The page snapshot
showed a fresh Home with the panel closed. Root cause: `finishWizard()` closed the wizard and
revealed the shell immediately, then awaited `settings.set` and `refreshBoot()`, and only after
those finished called `setRoute('home')`. During that window the user could already type; the
delayed route assignment remounted Home and discarded local state. The fix sets the route before
the settings round-trip. Three consecutive URL tests passed after the change.

### Direct-media import bug found by the new Playwright test

The first URL-download test served a direct `lecture.mp4` over HTTP. Import metadata succeeded,
but transcription failed with `Requested format is not available` because `download_audio()`
asked only for audio-only formats and a direct MP4 has a single muxed stream. The fix falls back
to `b` and extracts M4A audio with FFmpeg. The test now imports the URL, downloads through
yt-dlp and gets a real local Whisper transcript in **16.8 s**.

### Design direction

The shell moved from the editorial serif "cutting room" to a private productivity desk: 248 px
rail, 64 px top bar, near-black graphite, Inter display, gold accent, 18–20 px workspace cards
and pill actions. Home is a real dashboard: hero copy, an active-project bench card, a four-step
cut rail, a KPI band of actual counts, a file/link start panel and recent projects. The supplied
film-frame "C" is used in the rail, boot leader and desktop icon set. The loading sheet remains a
film leader and now uses the same type and mark.

The updates page, project workspace, discovery cards and Studio were retained and restyled, not
rebuilt; all existing flows still pass their tests. No fake growth metric, no invented
percentage, no decorative AI imagery.

### Verification in this pass

```text
Engine tests                 111 passed, 1 skipped (67.2 s)
Desktop build + unit tests    clean; 33 unit tests passed
Playwright suite             4 passed (1.4 m): local flow, URL download, update, rate limit
Screenshots                  19 regenerated at 1440×900 plus loading and safe-zone shots
```
