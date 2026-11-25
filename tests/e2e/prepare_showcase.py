"""Build a deterministic showcase data directory for screenshots and UI tests.

This uses the real fixture, real local Whisper transcription and real FFmpeg rendering.
Candidate proposals are authored here (not produced by a live model) so screenshots are
stable and do not depend on an API key. That fact is recorded in the docs.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shorts_engine.api.app import EngineApp  # noqa: E402
from shorts_engine.api.methods.projects import import_file  # noqa: E402
from shorts_engine.api.params import ImportFileParams  # noqa: E402
from shorts_engine.discovery.boundaries import refine_boundaries  # noqa: E402
from shorts_engine.discovery.score import clip_fit  # noqa: E402
from shorts_engine.render.service import RenderHooks, RenderOptions  # noqa: E402


async def main(data_dir: Path) -> None:
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    app = EngineApp(data_dir)
    app.ctx.settings.set("wizard", {"completed": True})
    app.ctx.settings.set(
        "privacy",
        {
            "authorizationAcknowledgedAt": "2026-07-12T09:00:00Z",
            "providerDisclosureAt": "2026-07-12T09:00:00Z",
            "requestLogEnabled": True,
        },
    )
    project = app.ctx.projects.create("The quiet interview")
    fixture = ROOT / "tests/fixtures/demo-lecture.mp4"
    imported = await import_file(
        app, ImportFileParams(projectId=project["id"], path=str(fixture)), {}
    )
    source = imported["source"]

    # Reuse the already downloaded tiny model from the engineering data dir when available,
    # otherwise download it through the normal model manager.
    model_src = Path("/tmp/cwtrans/models/whisper/tiny")
    model_dst = app.ctx.paths.models / "whisper" / "tiny"
    if model_src.exists() and not model_dst.exists():
        shutil.copytree(model_src, model_dst)
        app.ctx.model_repo.upsert(
            "whisper",
            "tiny",
            str(model_dst),
            version="showcase",
            sha256=None,
            bytes_=sum(p.stat().st_size for p in model_dst.rglob("*") if p.is_file()),
            meta={"catalog": {"name": "tiny"}},
        )
    elif not app.ctx.models.path_for("whisper", "tiny"):
        await app.ctx.models.download("whisper", "tiny")
    transcript = await app.ctx.transcription.transcribe(
        source,
        engine="local_whisper",
        language="en",
        model_name="tiny",
        job_tmp=app.ctx.paths.tmp / "showcase-transcribe",
    )
    app.ctx.sources.update(source["id"], language="en")
    app.ctx.settings.set(
        "transcription",
        {
            "engine": "local_whisper",
            "localModel": "tiny",
            "cloudModel": "whisper-large-v3-turbo",
            "providerProfileId": "groq-default",
            "preferCaptions": True,
            "language": "en",
        },
    )
    run = app.ctx.runs.create(
        source["id"], transcript["id"], "groq-default", "openai/gpt-oss-20b", {}, "showcase"
    )
    segments = transcript["segments"]
    seg_by_key = {s["segKey"]: s for s in segments}
    picks = [
        {
            "start_key": "s0000",
            "end_key": "s0001",
            "category": "educational",
            "categories": ["educational"],
            "title": "Small moments become memorable stories",
            "rationale": "It sets up the idea, gives a concrete explanation, and lands on the line about small moments becoming stories.",
            "ratings": {
                "hook_strength": {"score": 4, "evidence": "Opens by naming the subject of the test directly."},
                "context_completeness": {"score": 5, "evidence": "The setup and the first lesson are both inside the range."},
                "ending_quality": {"score": 4, "evidence": "Stops after the explanation of curiosity."},
                "standalone_clarity": {"score": 5, "evidence": "Needs no earlier context."},
            },
            "weaknesses": ["The recording is a synthetic test voice."],
        },
        {
            "start_key": "s0001",
            "end_key": "s0002",
            "category": "insight",
            "categories": ["insight"],
            "title": "Start with a question people can repeat",
            "rationale": "The clip moves from the first lesson into the closing rule about a line people can repeat, so it ends on a usable takeaway.",
            "ratings": {
                "hook_strength": {"score": 3, "evidence": "Starts mid-thought with the first lesson."},
                "context_completeness": {"score": 4, "evidence": "The explanation follows immediately."},
                "ending_quality": {"score": 5, "evidence": "Ends on the repeatable line."},
                "standalone_clarity": {"score": 4, "evidence": "Mostly clear without earlier context."},
            },
            "weaknesses": ["The opening sentence assumes the previous lesson."],
        },
    ]
    made: list[dict] = []
    for pick in picks:
        start_seg = seg_by_key[pick["start_key"]]
        end_seg = seg_by_key[pick["end_key"]]
        boundary = refine_boundaries(
            start_s=start_seg["startS"],
            end_s=end_seg["endS"],
            segments=segments,
            source_end=float(source["durationS"]),
        )
        assert boundary, "fixture boundary should be valid"
        excerpt = " ".join(
            s["text"] for s in segments if s["endS"] > boundary.start_s and s["startS"] < boundary.end_s
        )[:400]
        cand = {
            **pick,
            "start_s": boundary.start_s,
            "end_s": boundary.end_s,
            "excerpt": excerpt,
            "signals": boundary.signals,
            "cat": pick["category"],
            "categories": pick["categories"],
            "ratings": pick["ratings"],
            "weaknesses": pick["weaknesses"],
        }
        cand["fit_score"] = clip_fit(cand["ratings"], cand["signals"])
        made.append(cand)
    made.sort(key=lambda c: c["fit_score"], reverse=True)
    for i, cand in enumerate(made):
        cand["rank"] = i + 1
        if i == 0:
            cand["categories"] = sorted(set(cand["categories"]) | {"best_overall"})
        app.ctx.candidates.insert(
            source["id"],
            run["id"],
            {
                "category": cand["cat"],
                "categories": cand["categories"],
                "start_s": cand["start_s"],
                "end_s": cand["end_s"],
                "title": cand["title"],
                "excerpt": cand["excerpt"],
                "rationale": cand["rationale"],
                "ratings": cand["ratings"],
                "weaknesses": cand["weaknesses"],
                "fit_score": cand["fit_score"],
                "signals": cand["signals"],
                "seg_start_key": cand["start_key"],
                "seg_end_key": cand["end_key"],
                "rank": cand["rank"],
            },
        )
    app.ctx.runs.finish(
        run["id"], state="succeeded", token_usage={"totalTokens": 0, "note": "showcase authored candidates"}
    )
    candidates = app.ctx.candidates.list(source["id"])
    selections = app.ctx.selections.set(project["id"], [c["id"] for c in candidates], None)
    presets = {p["name"]: p for p in app.ctx.presets.list()}
    for i, sel in enumerate(selections):
        preset = presets["Educational"] if i == 0 else presets["Storytelling"]
        app.ctx.edits.set(sel["id"], preset["settings"])
    app.ctx.edits.set(
        selections[0]["id"],
        {
            "metadata": {
                "title": "Why small moments become memorable stories",
                "description": "A short lesson on turning a small moment into a story people remember.",
                "hashtags": ["#storytelling", "#shorts", "#clips"],
            }
        },
    )
    app.ctx.settings.set(
        "render",
        {
            "quality": "standard",
            "preferHardware": True,
            "filenameTemplate": "{title}-{index}-{start}",
            "fps": 30,
            "outputDir": str(app.ctx.paths.outputs),
        },
    )
    hooks = RenderHooks(cancel=asyncio.Event(), progress=lambda *a: None, log=lambda *a: None)
    result = await app.ctx.render.render_batch(
        project_id=project["id"],
        selection_ids=[selections[0]["id"]],
        options=RenderOptions(output_dir=app.ctx.paths.outputs),
        hooks=hooks,
        job_tmp=app.ctx.paths.tmp / "showcase-render",
    )
    print(json.dumps({
        "data_dir": str(data_dir),
        "project_id": project["id"],
        "source_id": source["id"],
        "transcript_id": transcript["id"],
        "candidates": [{"title": c["title"], "start": c["startS"], "end": c["endS"], "fit": c["fitScore"]} for c in candidates],
        "render": result,
    }, indent=2))
    app.ctx.db.close()


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/cw-showcase/engine")
    asyncio.run(main(target))
