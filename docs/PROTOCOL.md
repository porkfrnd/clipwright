# Engine protocol (v1)

Transport: newline-delimited JSON (NDJSON) over the engine process's stdin/stdout. One JSON
object per line. UTF-8, no BOM, no pretty printing. Logs go to stderr and to
`<data>/logs/engine.log`; they never share stdout with protocol messages.

Generated schemas: `schemas/protocol.schema.json`, `schemas/methods.json`, and
`apps/desktop/src/shared/schemas.generated.ts`. Regenerate with `scripts/gen-schemas`.

## Envelope

Request (app → engine):

```json
{"v":1,"id":"req-7","kind":"request","method":"project.list","params":{}}
```

| Field | Type | Notes |
| --- | --- | --- |
| `v` | integer | Must be `1`; anything else returns `ENGINE_PROTOCOL_MISMATCH`. |
| `id` | **string** | Correlates the response. The engine echoes it exactly. |
| `kind` | string | `request` (default). |
| `method` | string | Registered method name. |
| `params` | object | Validated by that method's Pydantic model; unknown fields are rejected (`extra="forbid"`). |
| `secrets` | object | Optional. Only provider/test/transcription methods read `apiKey` from here; secrets are never persisted in params or logs. |

Success response:

```json
{"v":1,"id":"req-7","kind":"response","result":{"projects":[]}}
```

Error response:

```json
{
  "v":1,
  "id":"req-7",
  "kind":"response",
  "error":{
    "code":"PROVIDER_AUTH_FAILED",
    "message":"The provider rejected the API key.",
    "details":{},
    "retryable":false
  }
}
```

Exactly one of `result` or `error` is present. A response may arrive before the request that
caused an event; clients must dispatch by `id` and handle `kind:"event"` asynchronously.

Events (engine → app), e.g. job progress:

```json
{"v":1,"id":"","kind":"event","method":"job.progress","params":{"jobId":"…","stage":"transcribing","fraction":0.42,"message":"Transcribing audio"}}
```

## Handshake

The supervisor must call `engine.hello` before anything else:

```json
{"v":1,"id":"req-1","method":"engine.hello","params":{"protocolVersion":1,"appVersion":"0.2.0"}}
```

Result:

```json
{
  "engineVersion":"0.2.0",
  "protocolVersion":1,
  "productName":"Clipwright",
  "capabilities":["…"],
  "dataDir":"/home/user/.config/Clipwright/engine",
  "platform":"linux",
  "python":"3.12.12"
}
```

`engine.ping` returns `{"pong": true}`. `engine.shutdown` asks the process to exit after
killing child processes. The supervisor kills the process group if graceful shutdown does
not finish.

## Methods

### Engine and system

| Method | Params | Result |
| --- | --- | --- |
| `engine.hello` | `protocolVersion`, `appVersion` | Engine info / mismatch error |
| `engine.ping` | — | `pong` |
| `engine.shutdown` | — | — |
| `hardware.detect` | — | CPU/RAM/disk/GPU/encoder report + recommended profile |
| `diagnostics.export` | — | Redacted diagnostics bundle path |
| `privacy.log` | — | Redacted request log |
| `privacy.clear` | — | Clears request log |
| `jobs.list` | — | Jobs |
| `jobs.get` | `jobId` | Job state, progress, checkpoint, error |
| `jobs.cancel` | `jobId` | Cancellation accepted |
| `jobs.resume` | `jobId` | Resumes from checkpoint |
| `binaries.status` | — | Paths/versions of ffmpeg, ffprobe, yt-dlp, Deno |
| `binaries.update` | — | Replaces yt-dlp after checksum verification |

### Settings, providers, models

| Method | Params | Result |
| --- | --- | --- |
| `settings.get` | optional `key` | All settings or one section |
| `settings.set` | `key`, `value` | Updated settings |
| `provider.list` | — | Profiles + default profile ID |
| `provider.save` | `profile` (no API key) | Saved profile |
| `provider.delete` | `profileId` | — |
| `provider.test` | `profileId` or ad-hoc endpoint, `probe` | Capability/auth result |
| `provider.list_models` | `profileId` | Provider models (with fallback) |
| `models.list` | — | Catalog + install state |
| `models.download` | `kind`, `name` | Download starts/progress events |
| `models.verify` | `modelId` | Hash verification result |
| `models.delete` | `modelId` | — |

API keys are never accepted in `provider.save`. The desktop stores them in `safeStorage`
and adds `{"apiKey":"…"}` to the `secrets` field only on the request that needs it.

`models.download` accepts `kind: "whisper" | "face" | "llm"`. The `llm` catalog currently
contains `qwen3-0.6b`, a pinned 610 MiB GGUF downloaded from Hugging Face and verified by
size and SHA-256.

A local provider uses `adapter: "local"` and `baseUrl: "local://qwen3-0.6b"` (or the model
name in `defaultModel`). `provider.save` derives the opaque local URL from the model and
never performs an HTTP request. `provider.test` loads the GGUF in-process and runs a small
JSON probe; no `secrets.apiKey` is needed. The adapter is `llama-cpp-python` bundled in the
engine, and the model file lives in the user data directory, not in the installer.

### Projects, sources, transcription

| Method | Params | Result |
| --- | --- | --- |
| `project.create` | `name` | Project |
| `project.list` | — | Projects with counts |
| `project.open` | `projectId` | Project + sources/last state |
| `project.rename` | `projectId`, `name` | Project |
| `project.delete` | `projectId` | — |
| `source.import_file` | `projectId`, `path` | Source (validated/probed) |
| `source.import_url` | `projectId`, `url`, `authorizationAckAt` | Source metadata (yt-dlp) |
| `source.get` | `sourceId` | Source + assets |
| `source.probe` | `sourceId` | Fresh ffprobe metadata |
| `source.preview` | `sourceId` | Secured preview asset |
| `source.fetch_preview` | `sourceId`, `startS`, `endS` | Selective URL retrieval |
| `source.set_authorization` | `sourceId`, `authorizationAckAt` | Updated source |
| `transcription.start` | `sourceId`, engine/model/language/provider, `preferCaptions` | Job |
| `transcript.get` | `sourceId`, optional `includeWords` (default `true`) | Transcript, segments, words; `false` omits word rows for fast Project reads |
| `transcript.list` | `sourceId` | Available transcripts |

### Discovery, edits, selection, metadata

| Method | Params | Result |
| --- | --- | --- |
| `analysis.start` | `sourceId`, provider/model/options | Job |
| `analysis.list` | `projectId` | Analyses |
| `analysis.estimate` | `sourceId`, provider/model | Requests/tokens estimate, including batched windows |
| `candidates.list` | `sourceId` | Candidates, ratings, categories |
| `candidates.update_bounds` | `candidateId`, `startS`, `endS` | Updated candidate; records a revision |
| `candidates.revisions` | `candidateId` | Earlier boundary edits, newest first |
| `candidates.undo` | `candidateId` | Restores newest revision and deletes it |
| `candidates.rename` | `candidateId`, `title` | Updated candidate |
| `candidates.set_status` | `candidateId`, `status` | Updated candidate |
| `selection.set` | `projectId`, `candidateIds`, optional `presetId` | Selections |
| `selection.list` | `projectId` | Selections + edits |
| `edit.get` | `selectionId` | Edit settings |
| `edit.set` | `selectionId`, settings | Updated edit |
| `preset.list` / `preset.save` / `preset.delete` | preset | Presets |
| `metadata.generate` | `selectionId`, provider/model | Title/description/hashtags |

### Render

| Method | Params | Result |
| --- | --- | --- |
| `render.start` | `projectId`, `selectionIds`, `outputDir`, quality/preferHardware/template | Job |
| `render.queue` | `projectId` | Queue/output records |

## Media access

The engine never exposes filesystem paths to the renderer. The main process registers asset
IDs and serves them through `media://<assetId>` with Range support; see `src/main/media.ts`.

## Jobs and progress

Job states: `queued`, `running`, `waiting_rate_limit`, `interrupted`, `succeeded`,
`failed`, `cancelled`.

Progress events use plain-language stages, a true fraction and a message:

```json
{"jobId":"…","stage":"rendering","fraction":0.63,"message":"Rendering clip 2 of 3"}
```

A 429 with `retry-after` moves the job to `waiting_rate_limit`, stores the retry time in the
checkpoint and resumes automatically. The UI shows a countdown and tells the user the window
may be closed; the engine continues and the job survives restart as `interrupted` with a
Resume action. Analysis checkpoints per window; render checkpoints per selection.

## Error codes

Codes are stable UPPER_SNAKE strings. User-facing `message` is plain language; `details`
contains structured, non-secret context. Representative codes:

`ENGINE_PROTOCOL_MISMATCH`, `METHOD_NOT_FOUND`, `INVALID_PARAMS`, `INTERNAL_ERROR`,
`PROJECT_NOT_FOUND`, `SOURCE_NOT_FOUND`, `SOURCE_UNSUPPORTED`, `SOURCE_DOWNLOAD_FAILED`,
`URL_INVALID`, `FILE_NOT_FOUND`, `FILE_TOO_LARGE`, `MEDIA_INVALID`, `MEDIA_TOO_LONG`,
`TRANSCRIPT_NOT_FOUND`, `TRANSCRIPT_EMPTY`, `MODEL_NOT_FOUND`, `MODEL_REQUIRED`,
`MODEL_VERIFY_FAILED`, `PROVIDER_NOT_FOUND`, `PROVIDER_AUTH_FAILED`,
`PROVIDER_BAD_RESPONSE`, `PROVIDER_URL_INVALID`, `SECRET_IN_PARAMS`, `NOTHING_TO_UNDO`,
`CANDIDATE_NOT_FOUND`, `INVALID_RANGE`, `CLIP_TOO_SHORT`, `CLIP_TOO_LONG`,
`NOTHING_SELECTED`, `OUTPUT_NOT_WRITABLE`, `OUTPUT_INVALID`, `RENDER_FAILED`,
`JOB_NOT_FOUND`, `JOB_NOT_RESUMABLE`, `JOB_CANCELLED`, `CANCELLED`.

API keys must never appear in errors, logs or diagnostics. `diagnostics.export` and
`privacy.log` run the redaction layer before returning data.

## CLI mode

The same engine can run without stdio:

```bash
.venv/bin/python -m shorts_engine run-job transcription \
  --params '{"sourceId":"…"}' --data-dir /tmp/clipwright-engine
```

This is used by tests and the packaged-engine smoke check. It shares jobs, storage and
render code with the GUI path; it does not import Electron.
