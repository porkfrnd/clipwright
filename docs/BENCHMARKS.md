# Benchmarks

Measured on the development machine with a single run per task. These are estimates,
not guarantees. Software encoding only; no usable GPU was detected.

- CPU: Intel(R) Core(TM) i5-6200U CPU @ 2.30GHz
- Cores: 4
- OS: Linux-6.12.113+deb13-amd64-x86_64-with-glibc2.41
- Python: 3.12.12
- FFmpeg: system 7.1.5 development build; packaged builds use the bundled 7.0.2 static build
- Whisper: tiny, int8, CPU, VAD on, word timestamps on

| Task | Content | Wall time | Speed | Peak RSS |
| --- | --- | --- | --- | --- |
| Local transcription (tiny) | 13s speech | 8.7s | 1.49× real-time | 447 MB (engine process) |
| Render 1080×1920 H.264/AAC | 15.8s clip | 18.0s | 0.88× real-time | 722 MB (ffmpeg child) |

Interpretation: this CPU-only laptop is a low-resource baseline. Longer clips cost roughly
linearly in encoding time. Local transcription at ~1× real-time means a 60-minute recording
takes about an hour with `tiny`; larger models are slower. Cloud transcription is the fast path
on this hardware, and the app recommends it for the low-resource profile.

Reproduce with `scripts/benchmark`. Numbers will vary with thermal state, source content and
FFmpeg build.

## Interaction/network observations (2026-11-24)

These are single-run observations on the same machine, using the packaged build and the real
test project. They are not a formal benchmark.

| Operation | Observed |
| --- | --- |
| Packaged cold start → Home visible | 1.9 s |
| `binaries.status` after manifest-version fix | ~80 ms cold, ~28 ms cached (was ~2.3 s) |
| Real 626 s YouTube source using existing captions | ~52 s end-to-end, 295 segments |
| Local Whisper tiny on the same source (earlier run) | ~7 min |
| Software 1080×1920 render, 20 s clip | ~18 s in the render benchmark |

The caption path is preferred when captions exist. If caption endpoints return 429, Clipwright
keeps any successfully downloaded language and otherwise falls back to audio transcription.

## Hot-path optimization pass (2026-11-24)

Single-run measurements on the build machine, using the real 626 s speech asset and the
installed `tiny` Whisper model unless noted.

| Operation | Before | After |
| --- | ---: | ---: |
| Transcript save (295 segments, 1,475 words) | 2.105 s | 0.072 s |
| Transcript read, full words (170 segments, 1,976 words) | ~78 ms cold | ~17 ms warm |
| Project transcript read, no words | ~17 ms | ~1 ms |
| Local Whisper, 626 s, beam 5 → beam 1 | 66.8 s | 40.4 s |
| First local transcription end-to-end | ~75 s | 43.5 s |
| Repeat local transcription (prepared audio) | re-extract | 0.33 s |
| Concurrent identical preview requests | 2 downloads | 1 download |
| Engine import (`api.app`) | ~502 ms | ~281 ms |
| Engine cold `hello` | ~649 ms | ~610 ms |

These are single-run development measurements, not guarantees. The largest changes are the
SQLite bulk write, greedy CPU Whisper and prepared-audio reuse; end-to-end gains depend on
whether captions exist and whether a source was transcribed before.

## Local AI (Qwen3 0.6B Q8_0, CPU, 2026-11-24)

Measured with the frozen engine and the real 610 MiB GGUF on the same 4-core CPU. These are
single-run observations, not a quality benchmark.

| Operation | Observed |
| --- | ---: |
| First model load + tiny JSON probe (`provider.test`) | 3.6–6.7 s |
| Subsequent JSON probe after load | ~0.9 s |
| Metadata generation (schema-valid title/description/hashtags/hooks) | 24.0 s |
| Real `find_moments`, 26 s / 3 segments (1 valid candidate) | 88.5 s / 1,547 tokens |
| Model file | 639,446,688 bytes |
| Runtime | `llama-cpp-python` 0.3.38, CPU only, `n_ctx=16384` |

The 0.6B model is intended for offline/privacy-first use, not as a speed or quality match for
a hosted model. The first analysis pays model load; the adapter keeps the loaded model for the
engine process.

## Rate-limit batching (2026-11-24)

Measured from the stored 626 s source transcript on this machine:

| Layout | Windows | Provider map requests | Approx. transcript input tokens |
| --- | ---: | ---: | ---: |
| Previous | 2 (360 s each) | 2 | 3,209 (with overlap) |
| Batched | 2 | 1 | 2,857 (overlap de-duplicated) |

This saves one system prompt, the overlapping text, and one completion budget. It does not
increase the provider’s quota; a batch still consumes tokens. The prior adapter also added its
local estimate on top of the provider’s token headers, which could force an unnecessary wait
after the first request; that double-count is fixed.

The real Qwen3 0.6B GGUF downloaded through `ModelManager.download` in **239 s** on this
connection; the 639,446,688-byte file was verified before registration. Local inference has no
provider rate limit.
