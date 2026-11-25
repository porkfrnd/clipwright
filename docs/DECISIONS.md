# Decisions

ADR-style records for choices that are not obvious from the code. Dates are UTC.

## ADR-001 — Python engine, Electron shell, one NDJSON protocol

**Context.** AI/media work needs Python libraries (faster-whisper, ctranslate2, PyAV/OpenCV,
FFmpeg); the required UI stack is Electron + Svelte. Rewriting either side in the other
language would be slower and less reliable.

**Decision.** Ship two programs: Electron (main + sandboxed renderer) and a Python engine
speaking NDJSON over stdio. The engine is independently runnable as
`python -m shorts_engine --stdio` and as a frozen executable. No AI/media work in Node; no
Rust.

**Consequences.** One process boundary to secure and debug; the engine can be tested
headlessly; packaging must freeze Python and its native libraries. The protocol is versioned
and its schemas are generated.

## ADR-002 — Protocol IDs are strings; methods are allow-listed twice

**Context.** JavaScript numbers lose precision above 2^53; the renderer must not gain a
generic “call any method” bridge.

**Decision.** `Request.id` and `Response.id` are strings. The engine validates params with
Pydantic (`extra="forbid"`). Electron's preload/main allow-lists every method and validates
trusted sender frames. Protocol version mismatch is an explicit error.

**Consequences.** No numeric-ID coercion bugs; unknown methods fail closed at both layers.
Adding a method requires regenerating schemas and updating the allow-list.

## ADR-003 — Bundle tools at build time, not in git

**Context.** FFmpeg, yt-dlp, and Deno are large and platform-specific; committing binaries
bloats the repository and obscures provenance.

**Decision.** `resources/bin/MANIFEST.json` pins URL, SHA-256, archive/member, license and
source. `scripts/fetch-binaries` verifies and installs atomically. Builds bundle the files
under `resources/bin/<platform>/`; packaged apps put them beside the frozen engine.

**Consequences.** Builds require network once; hashes are auditable; updates are explicit.
Development can fall back to system tools. A stale manifest is a release blocker.

## ADR-004 — GPL FFmpeg invoked as a subprocess

**Context.** H.264 via libx264 and subtitle burn-in via libass require a GPL FFmpeg build.

**Decision.** Bundle a GPL-2.0-or-later static FFmpeg 7.0.2 and invoke `ffmpeg`/`ffprobe` as
separate executables. Never link FFmpeg into Clipwright. Ship `THIRD_PARTY_LICENSES.md`,
license texts and a corresponding-source link.

**Consequences.** Redistribution must comply with GPL. **Commercial redistribution needs a
human legal review** and a source-code offer plan. The app itself remains MIT.

## ADR-005 — SQLite WAL with explicit checkpoints

**Context.** Jobs can take minutes; cancellation, crashes and engine restarts must not corrupt
projects or lose completed analysis.

**Decision.** Use SQLite with WAL, foreign keys and transactions. Migrations are numbered.
Analysis checkpoints per transcript window; render checkpoints per selection. Jobs persist
states (`queued`, `running`, `waiting_rate_limit`, `interrupted`, `succeeded`, `failed`,
`cancelled`).

**Consequences.** Resume is possible after an engine restart. The database is the source of
truth, not in-memory job objects. The UI must handle `interrupted` explicitly.

## ADR-006 — Brand is generated from one constant

**Context.** The product name must exist in exactly one config.

**Decision.** `engine/shorts_engine/common/brand.py` owns `PRODUCT_NAME`,
`PROTOCOL_VERSION`, `ENGINE_VERSION`. `scripts/gen-brand` writes
`apps/desktop/src/shared/brand.generated.ts`; `brand.ts` re-exports it. `scripts/gen-schemas`
refuses to run when the mirror is stale.

**Consequences.** Renaming the product is a one-line change plus regeneration. Build/test
fails loudly if the mirror drifts.

## ADR-007 — Local Whisper through faster-whisper; FFmpeg decode path

**Context.** faster-whisper expects decoded audio and gives word timings. PyAV decoding of
the test fixtures was unreliable in the engine environment.

**Decision.** Decode with bundled/system FFmpeg to 16 kHz mono float32 PCM, then feed
faster-whisper. Model files are pinned by Hugging Face revision; downloads are verified and
atomically activated. Models are released after transcription.

**Consequences.** Extra disk I/O and a dependency on the FFmpeg binary (already required).
The path is deterministic and handles arbitrary containers. Only `tiny` was downloaded and
exercised in this environment; other models are catalog-only until downloaded.

## ADR-008 — Capability ladder and honest degradation

**Context.** OpenAI-compatible endpoints differ in JSON-schema support.

**Decision.** Probe/reuse provider capabilities and degrade in order:
`json_schema` (strict) → `json_object` → prompt-only JSON. Validation always runs. Auth
failures and malformed responses are not silently “degraded”; they surface with stable
codes. A failed ranking call keeps deterministic Clip fit.

**Consequences.** More provider compatibility without pretending validation is optional.
Degradation is recorded in the request log.

## ADR-009 — Token-bucket rate limiter plus retry-after handling

**Context.** Groq and compatible providers enforce request/token limits and return compound
durations (e.g. `2m59.56s`, `1h2m3s`).

**Decision.** A token-bucket scheduler reserves request and token capacity; 429 responses
parse `retry-after`/reset headers (including compound forms), move the job to
`waiting_rate_limit`, checkpoint, and resume automatically. Cancellation is checked before
provider calls.

**Consequences.** Waits are visible and survivable. A fake 429 with a short retry was tested;
a real provider 429 was not available without a key.

## ADR-010 — Discovery validation is authoritative; Clip fit is deterministic

**Context.** LLMs can return plausible but invalid ranges, invented segment IDs, or text that
looks like instructions.

**Decision.** Candidates may only reference `s\d{4,6}` segment IDs. Validate ranges, clamp to
source duration, snap boundaries to word/sentence/silence edges, enforce 15–90 s, dedupe by
IoU, then score:

`55% ratings + 25% boundary quality + 12% duration fit + 8% speech continuity`.

The model cannot execute actions. Prompt text treats transcripts as untrusted data.

**Consequences.** Some valid model ideas are rejected; every surviving candidate is playable
and explainable. Scores are reproducible without the model.

## ADR-011 — Render contract: 1080×1920, H.264 High, AAC 192k, loudnorm

**Context.** Shorts platforms need predictable vertical output; the app must validate rather
than trust FFmpeg exit codes.

**Decision.** 1080×1920, 30 fps, H.264 High/yuv420p, AAC 192 kbps 48 kHz stereo,
`+faststart`, single-pass `loudnorm I=-14 TP=-1.5 LRA=11`. Render to `.part`, probe, decode
to null, then atomically rename. Cancel kills the process group and deletes partial files.

**Consequences.** Output is platform-ready and verifiable. Encoding is slower than a
one-pass “good enough” export; the low-resource profile uses `veryfast`. Hardware encoders
are preferred only after a test encode succeeds.

## ADR-012 — No face tracking in the MVP build

**Context.** Face tracking and active-speaker framing are advanced scope after MVP gates.
YuNet is small and pinned, but reliable tracking/smoothing and speaker selection need more
validation than the schedule allowed.

**Decision.** Ship fill, blur-fill and manual center crop with static zoom. Keep the YuNet
catalog entry and hardware detection; do not claim face tracking in the UI or docs.

**Consequences.** Talking-head footage is cropped from the center; users can adjust zoom.
The UI explicitly says face tracking is not enabled. This is a known limitation, not a
hidden failure.

## ADR-013 — Secrets in Electron safeStorage, never SQLite

**Context.** BYOK keys must not appear in the renderer after save, logs, SQLite or diagnostics.

**Decision.** Encrypt in main with Electron `safeStorage` async API; store ciphertext on disk.
On Linux, if the selected backend is `basic_text` or encryption is unavailable, default to
session-only keys and require a warned opt-in for weak storage. Renderer receives only
status/masked metadata. Engine gets a key only in the transient `secrets` field of the request
that needs it. `GROQ_API_KEY` is supported as a read-only developer convenience.

**Consequences.** Some Linux desktops cannot persist a key without a keyring; the UI explains
this. CI/headless tests use a test user-data directory, not real secrets.

## ADR-014 — JSON round-trip at the renderer IPC boundary

**Context.** Svelte 5 `$state` values are Proxies, which Electron's structured clone rejects
(“An object could not be cloned”).

**Decision.** `lib/api.ts` serializes params through `JSON.parse(JSON.stringify(...))` before
`window.clipwright.request`; the preload does the same defensively. Requests carry plain data
only.

**Consequences.** Reactive state can be passed directly; non-JSON values (functions, Dates)
are intentionally unsupported at the boundary.

## ADR-015 — Playwright is the UI acceptance test; screenshots are real data

**Context.** Unit tests cannot prove that the wizard, native dialog path, preview, render
queue and security flags work together.

**Decision.** One long Playwright Electron flow covers wizard → local import → real tiny
Whisper → provider stub → analysis → selection → boundary edit/undo → Studio → real FFmpeg
export → security assertions. A second packaged run uses `release/linux-unpacked/clipwright`
with an empty `PATH`. Screenshots are captured from a real Electron window using a real
fixture, real local Whisper and a real render; showcase candidates are authored and labeled
as such.

**Consequences.** Tests are slower but meaningful. A stub provider proves control flow, not
real model quality; the distinction is stated in the devlog and known issues.

## ADR-016 — Stub AI is control-flow evidence only

**Context.** No `GROQ_API_KEY` was set in the environment. Live tests cannot run.

**Decision.** Use a local OpenAI-compatible stub server for integration/UI control flow, with
strict labels. Do not claim the real AI pipeline is verified. Keep a `live` pytest marker for
the real endpoint.

**Consequences.** Discovery quality against Groq is unverified. The first user action should
be to add a key and run a real analysis; the Settings/Wizard copy says so.

## ADR-017 — Linux-only packaging in this environment; Windows unverified

**Context.** The build host is Debian 13 x86_64. electron-builder can cross-configure Windows
NSIS, but a clean Windows VM and signing certificates are not available here.

**Decision.** Ship and verify Linux AppImage + `.deb` and the unpacked app. Keep Windows/macOS
configuration paths compatible, but do not claim a Windows build or clean-VM test.

**Consequences.** Acceptance item 12 is demonstrated on Linux only; Windows remains a release
task requiring a Windows build host/VM. `docs/RELEASE.md` states this.

## ADR-018 — No silent auto-updates

**Context.** App updates and yt-dlp updates have different risk profiles; silent updates can
break BYOK setups or downloads.

**Decision.** `electron-updater` is present, but no publish provider/update channel is
configured in this build. yt-dlp has an explicit update action with checksum verification.
Never update silently.

**Consequences.** Users update manually until a release feed and signing are configured.
This is documented in `KNOWN_ISSUES.md`.

## ADR-019 — Boot recovery is owned by the renderer and supervisor together

**Context.** A transient engine restart could leave the boot screen permanently on “The media
engine could not start”, with a live engine process. The supervisor rejected requests on stale
child exits, and the renderer skipped boot completion when `booted` was already true.

**Decision.** Treat engine readiness as a recoverable state:

- only the current child may reject requests or schedule a restart; stale exits/hello
  callbacks are ignored;
- the renderer polls status while the boot screen is visible, retries `refreshBoot`, and
  finishes the shell from already-loaded state;
- expose an explicit `engine.restart` that resets the restart budget and kills/restarts the
  child;
- expose the engine log on failure, write `logs/main.log`, and auto-reload a crashed renderer
  at most twice.

**Consequences.** The user can recover without a terminal; a genuinely broken engine still
shows a clear log and a Restart button. The supervisor is slightly more stateful, so stale
callbacks must continue to be guarded whenever new child processes are introduced.

## ADR-020 — Cache rows expose parsed metadata; YouTube retries are bounded

**Status:** accepted (2026-11-23)

Repository list methods must return the same parsed JSON fields as their single-row
counterparts. `AssetRepo.for_source()` now parses `meta_json` into `meta`; without this, every
preview and render cache lookup silently missed and re-downloaded the same YouTube sections.

Preview cache identity is `(source, kind=preview, requestedStart, requestedEnd)`, and the
returned `startS` is the actual start of the downloaded section (not the requested clip start).
Clients use that offset for subtitle timing.

YouTube network failures are handled with a bounded ladder: fresh extraction, alternate
`web_embedded`/`mweb` clients, progressive format, then the native full-download + local-cut
fallback. An optional Netscape `cookies.txt` is available for signed-in/age-gated videos; it is
stored locally and is never sent to an AI provider.

## ADR-021 — Hot paths batch SQLite, cache audio, and use lean transcript reads

**Status:** accepted (2026-11-24)

**Context.** End-to-end profiling found four avoidable costs:

- `TranscriptRepo.save()` committed once per segment and once per word. A 295-segment,
  1,475-word transcript took **2.1 s** and blocked the single shared SQLite connection.
- `TranscriptRepo.get()` issued one words query per segment. Project/Studio paid this even
  though Project only needs segment text and times.
- Local Whisper used beam 5 on CPU; a real 626 s source took **66.8 s**.
- Concurrent preview requests for the same range could both miss the cache and download
  duplicate sections.

**Decision.**

- Add `Database.transaction()` and write transcript segments/words with `executemany` in one
  transaction. `SelectionRepo.set()` uses the same transaction.
- Read segments and words with one grouped join. Add `transcript.get(... includeWords=false)`
  for Project; fetch words lazily only when snapping to a spoken word. Studio/analysis keep
  full transcripts.
- Use greedy decoding (`beam_size=1`) for CPU Whisper. Word timestamps remain enabled.
  Captions remain the preferred path when present.
- Reuse prepared WAV/FLAC assets before re-downloading or extracting audio, keyed by source
  hash and codec. A second local transcription of a 626 s source now takes **0.33 s** after the
  first run.
- Serialize identical preview requests with a per-range `asyncio.Lock` and re-check the cache
  inside the lock.
- Add migration 2 indexes for source/transcript/asset/candidate/selection/export/job lookups.
- Cache ffprobe results by path, size and mtime; refresh explicitly from `source.probe`.
- Skip the `fps=30` filter when the source is already ~30 fps.
- Lazy-load numpy, httpx, local/cloud transcription engines and provider adapters so Home and
  Settings do not pay their import cost.

**Consequences.** First local transcription is faster; repeated transcription is effectively
instant when audio is prepared. Greedy decoding trades a small amount of model search for a
large CPU speedup; captions are preferred and the UI never claims live-model quality. The
database migration is additive and idempotent. Exact word data still loads for Studio, render
and analysis.

## ADR-022 — Local AI is an in-process GGUF provider, not an HTTP lookalike

**Status:** accepted (2026-11-24)

**Context.** The app should work without a Groq key. A local model is also the only way to
offer analysis when the user deliberately keeps transcripts on the machine. Adding an Ollama
or LM Studio requirement would make the feature depend on another daemon and another install
step.

**Decision.** Add a `local` provider adapter backed by `llama-cpp-python` and a downloaded
GGUF file:

- Model Manager offers **Qwen3 0.6B Q8_0** (the smallest Qwen3 instruct model; 610 MiB
  download, ~1.1 GB RAM) with a pinned revision and SHA-256.
- The model runs in the engine process on CPU (`n_gpu_layers=0`), `n_ctx=16384`, with no
  network request and no API key. The runtime is bundled in the frozen engine.
- `local://<model>` is an opaque provider URL; it is validated separately from HTTP(S)
  endpoints and can never be used to reach a remote host.
- Local structured output is prompt-constrained and Pydantic-validated, with one repair
  attempt. It does not claim JSON-schema mode. Provider Test loads the model and runs a tiny
  JSON generation so a missing library or corrupt GGUF is reported before analysis.
- Qwen3's `/no_think` switch is appended to the user turn; the 0.6B model otherwise spends
  its output budget on reasoning instead of the JSON answer.

**Consequences.** Downloads are large (610 MiB) and CPU inference is slower and less nuanced
than Groq. The first request pays model load time; subsequent requests reuse the loaded model
for the life of the engine process. The local model is an explicit opt-in after download; a
missing model or missing runtime produces a setup error, not a startup failure. Local model
quality is not presented as equivalent to a larger cloud model, and live Groq remains the
recommended quality path when a key is available.

## ADR-023 — Batch transcript windows and trust provider usage counters

**Status:** accepted (2026-11-24)

**Context.** A 626 s Groq analysis used two overlapping 360 s windows and recorded 14,048
tokens. The adapter added a local estimated token count after applying the provider's
`x-ratelimit-*` snapshot, so the next call believed the minute budget was nearly full even
when the provider reported remaining capacity. Repeating system prompts and overlap also
wasted tokens.

**Decision.** Group adjacent transcript windows into provider requests (default 2, adjustable
1–4) and de-duplicate transcription segments by `segKey` inside each batch. Keep segment-ID
validation, boundary snapping, dedupe and ranking unchanged. Record actual `usage.total_tokens`
on successful calls; when the provider supplied token/request headers, do not add the local
estimate a second time.

**Consequences.** A two-window source uses one map request instead of two, with lower repeated
prompt/overlap cost. Batching can produce fewer candidates per source, and a batch still has
to fit the provider's context and TPM. This is not a way to exceed quota; the app continues to
wait and resume when a provider is genuinely rate-limited. Local Qwen remains the unlimited
offline fallback.
