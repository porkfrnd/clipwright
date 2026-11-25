from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from ..ai.adapter import AdapterHooks, OpenAICompatibleAdapter
from ..ai.contract import MomentAI, MomentWindow
from ..ai.prompts import PROMPT_VERSION
from ..ai.schemas import Category
from ..common.errors import CancelledError, EngineError
from ..common.util import format_timecode
from ..storage.repos import AnalysisRunRepo, CandidateRepo, SourceRepo, TranscriptRepo
from .boundaries import refine_boundaries
from .chunker import batch_windows, build_windows, window_lines
from .dedupe import dedupe_candidates, text_similarity
from .score import clip_fit, fit_explanation
from .validate import dicts_to_proposals, proposals_to_dicts, validate_proposals


@dataclass
class AnalysisOptions:
    max_candidates_per_window: int = 5
    window_seconds: float = 360.0
    overlap: float = 0.22
    min_duration: float = 15.0
    max_duration: float = 90.0
    rank_with_ai: bool = True
    batch_size: int = 2


@dataclass
class AnalysisHooks:
    progress: Callable[[str, float, str], None] = lambda stage, fraction, message: None
    state: Callable[[str], None] = lambda state: None
    wait: Callable[[float, str], Any] = lambda seconds, reason: None
    checkpoint: Callable[[dict[str, Any]], None] = lambda data: None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    request_log: Callable[[str, str | None, str, int, list[str], str], None] | None = None

    def adapter_hooks(self) -> AdapterHooks:
        return AdapterHooks(
            on_wait=self._on_wait,
            on_request=self.request_log,
            cancel=self.cancel,
        )

    async def _on_wait(self, seconds: float, reason: str) -> None:
        self.state("waiting_rate_limit")
        result = self.wait(seconds, reason)
        if asyncio.iscoroutine(result):
            await result


class DiscoveryPipeline:
    def __init__(
        self,
        *,
        runs: AnalysisRunRepo,
        candidates: CandidateRepo,
        transcripts: TranscriptRepo,
        sources: SourceRepo,
    ) -> None:
        self.runs = runs
        self.candidates = candidates
        self.transcripts = transcripts
        self.sources = sources

    async def run(
        self,
        *,
        source: dict[str, Any],
        transcript: dict[str, Any],
        adapter: OpenAICompatibleAdapter,
        provider_profile_id: str | None,
        model: str,
        options: AnalysisOptions,
        hooks: AnalysisHooks,
        checkpoint: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        checkpoint = dict(checkpoint or {})
        segments = transcript["segments"]
        if not segments:
            raise EngineError("TRANSCRIPT_EMPTY", "There is no transcript text to analyze.")
        source_end = float(source.get("durationS") or segments[-1]["endS"])
        transcript_end = float(segments[-1]["endS"])
        source_start = float(segments[0]["startS"])

        run_id = checkpoint.get("runId")
        if not run_id and persist:
            run = self.runs.create(
                source["id"],
                transcript["id"],
                provider_profile_id,
                model,
                {
                    "maxCandidatesPerWindow": options.max_candidates_per_window,
                    "windowSeconds": options.window_seconds,
                    "overlap": options.overlap,
                    "minDuration": options.min_duration,
                    "maxDuration": options.max_duration,
                    "rankWithAi": options.rank_with_ai,
                    "batchSize": options.batch_size,
                },
                PROMPT_VERSION,
            )
            run_id = run["id"]
            checkpoint = {"runId": run_id, "batchesDone": 0, "proposals": [], "tokens": 0}
            hooks.checkpoint(checkpoint)
        elif not run_id:
            # Comparison runs must not create an analysis run or candidate rows.
            run_id = "preview"
            checkpoint = {"runId": run_id, "batchesDone": 0, "proposals": [], "tokens": 0}
        elif persist:
            # A re-run of an interrupted job owns the same run.
            self.candidates.clear_for_run(run_id)

        windows = build_windows(
            segments, target_s=options.window_seconds, overlap=options.overlap
        )
        batches = batch_windows(windows, size=options.batch_size)
        checkpoint["windowCount"] = len(windows)
        checkpoint["batchCount"] = len(batches)
        hooks.progress(
            "chunking",
            0.04,
            f"Preparing {len(windows)} transcript windows in {len(batches)} batches.",
        )

        ai = MomentAI(adapter)
        tokens = int(checkpoint.get("tokens") or 0)
        proposals = list(checkpoint.get("proposals") or [])
        done = int(checkpoint.get("batchesDone") or 0)
        adapter_hooks = hooks.adapter_hooks()

        for batch in batches:
            if batch.index < done:
                continue
            if hooks.cancel.is_set():
                raise CancelledError()
            hooks.state("running")
            hooks.progress(
                "finding_moments",
                0.05 + 0.72 * batch.index / max(1, len(batches)),
                f"Reading transcript batch {batch.index + 1} of {len(batches)}…",
            )
            moment_window = MomentWindow(
                start_s=batch.start_s,
                end_s=batch.end_s,
                lines=window_lines(batch),
                start_key=batch.start_key,
                end_key=batch.end_key,
            )
            result, chat = await ai.find_moments(
                moment_window,
                title=source.get("title") or "Untitled",
                max_candidates=options.max_candidates_per_window,
                hooks=adapter_hooks,
            )
            tokens += chat.total_tokens or 0
            validation = validate_proposals(
                result.candidates,
                batch.segments,
                min_duration=options.min_duration,
                max_duration=options.max_duration,
                window_start=batch.start_s,
                window_end=batch.end_s,
                source_start=source_start,
                source_end=transcript_end,
            )
            if validation.errors and len(validation.errors) >= max(1, len(result.candidates)):
                # One repair round, feeding the exact validation errors back to the model.
                hooks.progress("repairing", 0.05 + 0.72 * batch.index / max(1, len(batches)),
                               "Fixing clip boundaries the AI proposed…")
                repaired, chat2 = await ai.find_moments(
                    moment_window,
                    title=source.get("title") or "Untitled",
                    max_candidates=options.max_candidates_per_window,
                    hooks=adapter_hooks,
                    note="\n".join(validation.errors[:10]),
                )
                tokens += chat2.total_tokens or 0
                validation = validate_proposals(
                    repaired.candidates,
                    batch.segments,
                    min_duration=options.min_duration,
                    max_duration=options.max_duration,
                    window_start=batch.start_s,
                    window_end=batch.end_s,
                    source_start=source_start,
                    source_end=transcript_end,
                )
            for proposal in validation.valid:
                proposals.append({"windowIndex": batch.index, **proposal.model_dump(mode="json")})
            checkpoint.update(
                {
                    "batchesDone": batch.index + 1,
                    "proposals": proposals,
                    "tokens": tokens,
                    "windowCount": len(windows),
                    "batchCount": len(batches),
                }
            )
            hooks.checkpoint(checkpoint)

        hooks.progress("refining", 0.8, "Snapping clip starts and ends to spoken words…")
        seg_by_key = {s["segKey"]: s for s in segments}
        refined: list[dict[str, Any]] = []
        for proposal in proposals:
            start_seg = seg_by_key.get(proposal.get("start_seg"))
            end_seg = seg_by_key.get(proposal.get("end_seg"))
            if not start_seg or not end_seg:
                continue
            boundary = refine_boundaries(
                start_s=float(start_seg["startS"]),
                end_s=float(end_seg["endS"]),
                segments=segments,
                min_duration=options.min_duration,
                max_duration=options.max_duration,
                source_end=source_end,
            )
            if not boundary:
                continue
            excerpt = " ".join(
                s["text"]
                for s in segments
                if float(s["endS"]) > boundary.start_s and float(s["startS"]) < boundary.end_s
            )[:400]
            ratings = {
                key: {
                    "score": int(value.get("score", 3)),
                    "evidence": str(value.get("evidence", "")),
                }
                for key, value in (proposal.get("ratings") or {}).items()
                if isinstance(value, dict)
            }
            refined.append(
                {
                    "category": proposal["category"],
                    "categories": [proposal["category"]],
                    "start_s": boundary.start_s,
                    "end_s": boundary.end_s,
                    "title": proposal["title"],
                    "excerpt": excerpt,
                    "rationale": proposal["rationale"],
                    "ratings": ratings,
                    "weaknesses": proposal.get("weaknesses") or [],
                    "signals": boundary.signals,
                    "seg_start_key": proposal["start_seg"],
                    "seg_end_key": proposal["end_seg"],
                }
            )
        deduped = dedupe_candidates(refined)
        for cand in deduped:
            cand["fit_score"] = clip_fit(cand["ratings"], cand["signals"])

        if not deduped:
            if persist:
                self.runs.finish(
                    run_id,
                    state="failed",
                    token_usage={"totalTokens": tokens},
                    error={
                        "code": "NO_VALID_CANDIDATES",
                        "message": "No clip candidates passed validation. Try a different model or a shorter source.",
                    },
                )
            raise EngineError(
                "NO_VALID_CANDIDATES",
                "The AI did not propose any clip that passed validation. Try another model, "
                "or analyze a shorter section of the video.",
                retryable=True,
            )

        # Reduce / rank step. The AI only reorders candidates that Python already validated.
        ranking: list[dict[str, Any]] = []
        if options.rank_with_ai and len(deduped) > 1:
            hooks.progress("ranking", 0.9, "Comparing clips…")
            summaries = [
                f"[{i + 1}] {c['seg_start_key']}-{c['seg_end_key']} | {c['durationS'] if 'durationS' in c else int(c['end_s'] - c['start_s'])}s | "
                f"{c['title']} | ratings: "
                + ", ".join(f"{k}={v.get('score')}" for k, v in c["ratings"].items())
                + f" | fit {c['fit_score']}"
                for i, c in enumerate(deduped)
            ]
            try:
                ranked, chat = await ai.rank_candidates(
                    title=source.get("title") or "Untitled", summaries=summaries, hooks=adapter_hooks
                )
                tokens += chat.total_tokens or 0
                valid_ranges = {(c["seg_start_key"], c["seg_end_key"]) for c in deduped}
                used = set()
                for item in ranked.ranking:
                    key = (item.start_seg, item.end_seg)
                    if key in valid_ranges and key not in used:
                        used.add(key)
                        ranking.append(
                            {
                                "start": item.start_seg,
                                "end": item.end_seg,
                                "rank": item.rank,
                                "best": item.best_overall,
                            }
                        )
            except CancelledError:
                raise
            except Exception as exc:
                hooks.progress("ranking", 0.92, "Ranking with fit signals instead.")
                checkpoint["rankFallback"] = str(exc)[:300]
        if not ranking:
            ordered = sorted(deduped, key=lambda c: c["fit_score"], reverse=True)
            ranking = [
                {"start": c["seg_start_key"], "end": c["seg_end_key"], "rank": i + 1, "best": i == 0}
                for i, c in enumerate(ordered)
            ]
        best = next((r for r in ranking if r.get("best")), ranking[0])
        for cand in deduped:
            match = next(
                (r for r in ranking if r["start"] == cand["seg_start_key"] and r["end"] == cand["seg_end_key"]),
                None,
            )
            cand["rank"] = match["rank"] if match else 999
            if match and match is best:
                cand["categories"] = sorted(set(cand["categories"]) | {Category.best_overall.value})
        deduped.sort(key=lambda c: c["rank"])

        if persist:
            self.candidates.clear_for_run(run_id)
            for cand in deduped:
                self.candidates.insert(source["id"], run_id, cand)
            self.runs.finish(
                run_id,
                state="succeeded",
                token_usage={
                    "totalTokens": tokens,
                    "candidates": len(deduped),
                    "windows": len(windows),
                    "batches": len(batches),
                    "promptVersion": PROMPT_VERSION,
                },
            )
        hooks.progress("done", 1.0, f"Found {len(deduped)} clip moments.")
        return {
            "analysisRunId": run_id,
            "persisted": persist,
            "candidates": deduped,
            "candidateCount": len(deduped),
            "windows": len(windows),
            "batches": len(batches),
            "tokens": tokens,
            "model": model,
            "fitExplanation": fit_explanation(),
        }
