import json
from pathlib import Path

import pytest

from shorts_engine.storage.db import Database
from shorts_engine.storage.repos import (
    AssetRepo,
    CandidateRepo,
    EditRepo,
    PresetRepo,
    ProjectRepo,
    SelectionRepo,
    SettingsRepo,
    SourceRepo,
    TranscriptRepo,
)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test.sqlite3")
    yield database
    database.close()


def make_transcript(repos, source_id):
    return repos["transcripts"].save(
        source_id,
        origin="local_whisper",
        engine="local_whisper",
        model="tiny",
        language="en",
        params={"beam_size": 5},
        cache_key="hash:tiny:en",
        word_timing="exact",
        segments=[
            {
                "seq": 0,
                "seg_key": "s0000",
                "start_s": 0.5,
                "end_s": 3.2,
                "text": "Hello world.",
                "words": [
                    {"seq": 0, "start_s": 0.5, "end_s": 1.5, "text": "Hello", "confidence": 0.9},
                    {"seq": 1, "start_s": 1.5, "end_s": 3.2, "text": "world.", "confidence": 0.8},
                ],
            }
        ],
    )


def test_migrations_are_idempotent(db):
    version = db.query_one("SELECT MAX(version) AS v FROM schema_migrations")
    assert version["v"] == 2
    db._migrate()
    assert db.query_one("SELECT COUNT(*) AS c FROM schema_migrations")["c"] == 2
    assert db.query_one("PRAGMA journal_mode")["journal_mode"].lower() == "wal"
    assert db.query_one("PRAGMA foreign_keys")["foreign_keys"] == 1


def test_project_and_source_persistence(db):
    projects = ProjectRepo(db)
    sources = SourceRepo(db)
    project = projects.create("  A room  ")
    assert project["name"] == "A room"
    source = sources.create(
        project["id"],
        kind="file",
        local_path="/tmp/a.mp4",
        title="A source",
        duration_s=42.5,
        width=1280,
        height=720,
        authorization_ack_at="2026-01-01T00:00:00Z",
    )
    assert source["durationS"] == 42.5
    reopened = ProjectRepo(db).get(project["id"])
    assert reopened["sources"][0]["title"] == "A source"
    assert projects.list()[0]["counts"]["sources"] == 1


def test_asset_lists_parse_metadata(db):
    project = ProjectRepo(db).create("P")
    source = SourceRepo(db).create(project["id"], kind="url", url="https://example.test/v")
    assets = AssetRepo(db)
    assets.add(
        source["id"],
        "preview",
        "/tmp/preview.mp4",
        start_s=10.0,
        end_s=22.0,
        meta={"requestedStart": 11.0, "requestedEnd": 21.0},
    )
    listed = assets.for_source(source["id"], "preview")
    assert listed[0]["meta"]["requestedStart"] == 11.0
    assert listed[0]["startS"] == 10.0
    assert "metaJson" not in listed[0]


def test_transcript_round_trip_and_cache(db):
    projects = ProjectRepo(db)
    sources = SourceRepo(db)
    transcripts = TranscriptRepo(db)
    project = projects.create("P")
    source = sources.create(project["id"], kind="file", local_path="/tmp/a.mp4")
    transcript = make_transcript(
        {"transcripts": transcripts},
        source["id"],
    )
    reloaded = transcripts.get(transcript["id"])
    assert reloaded["segments"][0]["segKey"] == "s0000"
    assert reloaded["segments"][0]["words"][0]["text"] == "Hello"
    assert reloaded["segments"][0]["words"][0]["startS"] == 0.5
    lean = transcripts.get(transcript["id"], include_words=False)
    assert lean["segments"][0]["text"] == "Hello world."
    assert lean["segments"][0]["words"] == []
    assert transcripts.latest_for_source(source["id"], include_words=False)["segments"][0]["words"] == []
    cached = transcripts.find_cached(source["id"], "hash:tiny:en")
    assert cached["id"] == transcript["id"]
    # Cache key uniqueness: a second save returns the same transcript.
    again = make_transcript({"transcripts": transcripts}, source["id"])
    assert again["id"] == transcript["id"]


def test_candidates_selections_and_edits(db):
    projects = ProjectRepo(db)
    sources = SourceRepo(db)
    transcripts = TranscriptRepo(db)
    candidates = CandidateRepo(db)
    project = projects.create("P")
    source = sources.create(project["id"], kind="file", local_path="/tmp/a.mp4")
    transcript = make_transcript({"transcripts": transcripts}, source["id"])
    run = db.execute(
        "INSERT INTO analysis_runs(id,source_id,transcript_id,provider_profile_id,model,params_json,prompt_version,started_at,state) VALUES('r1',?,?,?,?,?,?,?,'succeeded')",
        (source["id"], transcript["id"], "prov", "model", "{}", "v1", "2026-01-01T00:00:00Z"),
    )
    cid = candidates.insert(
        source["id"],
        "r1",
        {
            "category": "insight",
            "categories": ["insight", "best_overall"],
            "start_s": 0.5,
            "end_s": 20.0,
            "title": "A moment",
            "excerpt": "Hello world.",
            "rationale": "It works.",
            "ratings": {"hook_strength": {"score": 4}},
            "weaknesses": ["none"],
            "fit_score": 82.5,
            "signals": {"durationFit": 1.0},
            "seg_start_key": "s0000",
            "seg_end_key": "s0000",
            "rank": 1,
        },
    )
    listed = candidates.list(source["id"])
    assert listed[0]["fitScore"] == 82.5
    assert listed[0]["categories"] == ["insight", "best_overall"]
    assert listed[0]["ratings"]["hook_strength"]["score"] == 4

    candidates.update_bounds(cid, 1.5, 21.0, "user")
    revisions = candidates.revisions(cid)
    assert revisions and revisions[0]["startS"] == 0.5
    undone = candidates.undo(cid)
    assert undone["startS"] == 0.5
    assert candidates.revisions(cid) == []

    selections = SelectionRepo(db).set(project["id"], [cid], None)
    assert selections[0]["candidateId"] == cid
    edits = EditRepo(db)
    default = edits.get(selections[0]["id"])
    assert default["framing"]["layout"] == "fill"
    updated = edits.set(selections[0]["id"], {"metadata": {"title": "New"}, "framing": {"layout": "blur"}})
    assert updated["metadata"]["title"] == "New"
    assert updated["framing"]["layout"] == "blur"
    # Partial patches do not wipe untouched sections.
    assert updated["subtitles"]["enabled"] is True
    # Deleting the project cascades to sources, transcripts, selections.
    projects.delete(project["id"])
    assert sources.get(source["id"]) is None
    assert transcripts.get(transcript["id"]) is None
    assert SelectionRepo(db).list(project["id"]) == []


def test_settings_persist_and_presets_are_seeded(db):
    settings = SettingsRepo(db)
    settings.set("app", {"theme": "ember"})
    assert settings.get("app")["theme"] == "ember"
    assert settings.get("missing", {"x": 1}) == {"x": 1}
    presets = PresetRepo(db)
    from shorts_engine.render.presets import BUILTIN_PRESETS

    presets.seed(BUILTIN_PRESETS)
    names = [p["name"] for p in presets.list()]
    assert "Educational" in names
    with pytest.raises(ValueError):
        presets.save("Educational", {}, "preset-educational")
