# Architecture

Clipwright is two independently runnable programs joined by one protocol:

```text
┌──────────────────────────── Electron desktop ────────────────────────────┐
│  Svelte 5 renderer (sandboxed, no Node, no network)                      │
│      │ typed window.clipwright API (contextBridge)                       │
│  preload ── allow-listed IPC, zod params, trusted-sender checks           │
│      │                                                                   │
│  Electron main                                                           │
│    • engine supervisor (spawn, handshake, ping, restart, kill)           │
│    • safeStorage key vault     • media:// handler (registered IDs only)  │
│    • native dialogs            • engine subprocess lifecycle            │
│    • GitHub release check      • update state + trusted IPC             │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │ NDJSON over stdin/stdout (PROTOCOL v1)
┌───────────────────────────────▼──────────────────────────────────────────┐
│ Python engine — `python -m shorts_engine --stdio` or frozen executable   │
│  api/          method registry, params, jobs, events                     │
│  storage/      SQLite WAL schema + repositories                          │
│  ingest/       ffprobe, validation, yt-dlp, audio extraction             │
│  transcription/parsers, local faster-whisper, cloud Whisper, service      │
│  discovery/    windowing, prompt, validation, boundaries, dedupe, score  │
│  ai/           provider contract, capability ladder, rate limiter        │
│  render/       ASS subtitles, FFmpeg graph, queue, validation            │
│  models/       pinned downloads, verification, paths                     │
│  hardware/     CPU/RAM/GPU/encoder test encode                           │
└──────────────────────────────────────────────────────────────────────────┘
```

No AI, transcription, or media work runs in Node. No Rust is used. The renderer never
opens sockets or files: every action crosses the typed IPC bridge and, when it is media or
AI work, the stdio protocol.

## Process boundaries

| Boundary | Contract | Reason |
| --- | --- | --- |
| Renderer ↔ preload | `window.clipwright.request(method, params)` plus small typed helpers | The renderer has no Node integration; clipboard, dialogs, secrets and media URLs are explicit. |
| Preload ↔ main | allow-listed channels, zod validation, sender `webContents` + main-frame check | A compromised renderer cannot invoke arbitrary engine methods or shell commands. |
| Main ↔ engine | NDJSON request/response/event envelopes, protocol version handshake | The engine is independently testable and can be frozen without Electron. |
| Engine ↔ providers | OpenAI-compatible HTTP client with capability negotiation; optional in-process GGUF adapter | Provider choice cannot leak into transcript, discovery or render code. Local AI needs no socket or key. |
| Engine ↔ FFmpeg/yt-dlp | `spawn` argument arrays, no shell; process groups killed on cancel | Hostile media cannot inject commands; cancellation does not orphan children. |

## Startup and supervision

1. Electron main chooses `app.getPath('userData')/engine` as the engine data directory.
2. In development it starts `.venv/bin/python -m shorts_engine --stdio`; in a packaged
   build it starts `<resources>/engine/shorts-engine --stdio`, with bundled binaries on
   `PATH`.
3. The supervisor sends `engine.hello` with protocol version 1. A mismatch is a hard,
   visible error, not a silent retry.
4. A ping runs periodically. The supervisor restarts a dead engine with backoff and
   re-emits boot status; running jobs are recovered from SQLite as `interrupted`, and the
   UI offers Resume.
5. `engine.shutdown` closes the child on app quit.

## Update checks

The renderer never talks to GitHub. After the shell is usable, it calls the allow-listed
`updates:state` / `updates:check` IPC handlers. The main process fetches
`https://api.github.com/repos/porkfrnd/clipwright/releases/latest` with an 8 s timeout, a
`Clipwright/<version>` user agent, no credentials, and `redirect: 'error'`. Responses are
validated in `shared/updates.ts`: semver tags, `github.com` release URLs, allow-listed asset
hosts, bounded notes, and only recognized asset types for the current platform. Results are
cached for ten minutes; failures are silent outside the Updates page.

The page compares the tag to `app.getVersion()`, shows release notes as escaped plain text,
and opens the release page or asset in the system browser. It never downloads or executes an
installer. A dismissal is stored per version in renderer `localStorage`.

## Data and caching

The data directory contains:

```text
clipwright.sqlite3   WAL database
models/              Whisper models, YuNet
assets/<source>/     thumbnails, extracted audio, preview sections
outputs/             rendered clips (default; configurable)
tmp/<job>/           partial outputs, swept on boot
logs/                engine log with redaction
bin/                 optional downloaded tools
```

Everything is content-addressed or keyed by explicit IDs. Caching rules:

| Change | Invalidates | Keeps |
| --- | --- | --- |
| Subtitle style / preset | render output | transcript, candidates, selection |
| Candidate title / metadata | metadata only | transcript, boundaries, analysis |
| Boundary edit | that clip's preview/render | transcript and other candidates |
| Provider profile switch | future analysis calls | transcript, existing candidates, settings |
| Transcription re-run | transcript and candidates derived from it | project, source, exports |
| Source file content hash | all source-derived assets | project metadata |

A provider switch never discards a transcript. A style change never re-transcribes.
A title change never re-analyzes.

The local provider is the same application-level AI contract: `local://<model>` selects a
downloaded GGUF, which `llama-cpp-python` runs inside the engine process. The model file lives
under the user data directory; the runtime is part of the frozen engine. `provider.test`
performs a real JSON probe, and local structured calls validate with Pydantic like every other
provider. No API key or HTTP endpoint is involved.

## Storage schema (v1)

The migration creates roughly 25 tables, including:

- `projects`, `sources`, `assets`
- `transcripts`, `transcript_segments`
- `analyses`, `analysis_windows`, `candidates`, `candidate_ratings`,
  `candidate_categories`, `candidate_revisions`
- `selections`, `edit_settings`, `presets`
- `jobs`, `job_checkpoints`
- `provider_profiles`, `settings`, `schema_migrations`
- `render_outputs`, `request_log` (redacted)
- `model_installs`

SQLite runs with WAL, foreign keys and transactions. Jobs write checkpoints so a crash
mid-analysis or mid-render does not throw away completed windows or clips.

## Discovery pipeline

1. **Window** the transcript into overlapping windows (default 360 s, 22% overlap), then
   group adjacent windows into provider batches (default 2, de-duplicating overlap) to avoid
   repeated prompts and rate-limit pressure.
2. **Prompt** the provider with segment IDs (`s0001`…), timestamps and text; never raw
   timestamps as clip references. The prompt treats transcript text as data, not
   instructions.
3. **Parse and validate** strict JSON with Pydantic. Unknown fields are ignored; invalid
   IDs, reversed ranges and out-of-range times are rejected or repaired conservatively.
4. **Refine boundaries** to sentence and word edges using transcript word timings; widen to
   silence where available. Reject clips shorter than 15 s or longer than 90 s after
   refinement.
5. **Dedupe** overlapping proposals with IoU and content similarity.
6. **Rank** with the provider when enabled, then compute deterministic **Clip fit**:
   55% AI ratings, 25% boundary quality, 12% duration fit, 8% speech continuity. If the
   ranking call fails, deterministic order is retained and the failure is surfaced.
7. **Persist** candidates, ratings, evidence, weaknesses and categories. `best_overall` is
   assigned only from validated candidates.

The model can only *propose*. It cannot run a command, open a file, change settings or
trigger a render. Python validation is the authority.

## Render pipeline

1. Load selection + edit settings, resolve the source path, validate ranges and disk space.
2. Build an FFmpeg graph: 1080×1920, 30 fps, H.264 High, yuv420p, AAC 192 kbps 48 kHz
   stereo, `+faststart`, single-pass loudness normalization (`loudnorm -14 LUFS`, true peak
   −1.5 dB), optional background music with sidechain ducking.
3. Burn subtitles from a generated ASS file (word-level highlight when word timings exist;
   phrase-level otherwise). Fonts are bundled OFL faces.
4. Render to a `.part` file inside the job temp directory. On success: probe, validate
   duration/streams/pixels, then atomically rename into the output directory. On cancel or
   failure: kill the process group and remove the partial file.
5. Validate the finished file with ffprobe and a decode-to-null pass. The UI reports
   `succeeded` only after these checks pass.

Framing MVP is fill / blur-fill / manual center crop with static zoom. Face detection
exists in the model catalog but automatic face tracking is not enabled in this build.

## Security posture

- `sandbox: true`, `contextIsolation: true`, `nodeIntegration: false`, no `remote`, no
  `webviewTag`, `webSecurity` on, insecure content off.
- Strict CSP; renderer has no network access; `connect-src` is `self` (packaged) or
  localhost dev server.
- Navigation and new windows are blocked; only validated `https:`/`mailto:` links can open
  externally. Release links come from validated GitHub API data and are restricted to this
  repository's release host or allow-listed GitHub asset hosts before display.
- `media://` serves only asset IDs registered by the main process, with Range support and
  safe MIME types.
- API keys live only in Electron `safeStorage` ciphertext (or a session-only fallback on
  Linux with a weak backend), never in SQLite, logs or renderer state after save.
- Logs redact authorization headers, `gsk_…`/`sk-…` keys, query parameters and user paths
  when diagnostics are exported.
- Provider output is untrusted input: Pydantic validation, clamping, stable error codes and
  no tool execution.

## Extension points

- **Providers**: implement the adapter contract (`ai/adapter.py`) and register a profile.
- **Transcription**: implement the base engine (`transcription/base.py`) and add a service
  branch; parsers are shared.
- **Render presets**: preset settings are JSON; FFmpeg graph construction is centralized in
  `render/filters.py` and `render/encoder.py`.
- **Themes**: tokens in `app.css`; category color+glyph maps in `lib/categories.ts`.


## Performance hot paths

- **SQLite writes are grouped.** Transcript segments and words are inserted in one
  transaction; a full save is a bulk operation rather than thousands of commits.
- **Reads are page-shaped.** Project asks for transcript segments without word rows; Studio,
  render and analysis request the exact words they need.
- **Repeated audio is reused.** Prepared WAV/FLAC assets are keyed by source hash and codec,
  so a second transcription avoids network download and extraction.
- **CPU Whisper is greedy by default.** Captions are preferred when available; local audio
  transcription keeps exact word timestamps but uses beam 1 for CPU throughput.
- **Identical URL previews are single-flight.** A per-range lock prevents duplicate downloads
  when Project, Studio or Compare ask for the same section concurrently.
- **Indexes are migration-managed.** Migration 2 adds source/transcript/asset/candidate/
  selection/export/job indexes without rewriting existing data.
