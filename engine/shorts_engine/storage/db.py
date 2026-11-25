from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

now = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: E731

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_opened_at TEXT,
            state TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE sources (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('url','file')),
            url TEXT,
            local_path TEXT,
            content_hash TEXT,
            title TEXT NOT NULL DEFAULT '',
            channel TEXT,
            duration_s REAL,
            width INTEGER,
            height INTEGER,
            fps REAL,
            language TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            authorization_ack_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE assets (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            path TEXT NOT NULL,
            start_s REAL,
            end_s REAL,
            bytes INTEGER,
            created_at TEXT NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0,
            meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE transcripts (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            origin TEXT NOT NULL,
            engine TEXT NOT NULL,
            model TEXT,
            language TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            cache_key TEXT NOT NULL,
            word_timing TEXT NOT NULL DEFAULT 'exact',
            created_at TEXT NOT NULL,
            UNIQUE(source_id, cache_key)
        );
        CREATE TABLE segments (
            id TEXT PRIMARY KEY,
            transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            seg_key TEXT NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX idx_segments_transcript ON segments(transcript_id, seq);
        CREATE TABLE words (
            id TEXT PRIMARY KEY,
            segment_id TEXT NOT NULL REFERENCES segments(id) ON DELETE CASCADE,
            seq INTEGER NOT NULL,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            text TEXT NOT NULL,
            confidence REAL
        );
        CREATE INDEX idx_words_segment ON words(segment_id, seq);
        CREATE TABLE analysis_runs (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            transcript_id TEXT NOT NULL REFERENCES transcripts(id) ON DELETE CASCADE,
            provider_profile_id TEXT,
            model TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            prompt_version TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            token_usage_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'running',
            error_json TEXT
        );
        CREATE TABLE candidates (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            analysis_run_id TEXT NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
            category TEXT NOT NULL,
            categories_json TEXT NOT NULL DEFAULT '[]',
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            title TEXT NOT NULL,
            excerpt TEXT NOT NULL DEFAULT '',
            rationale TEXT NOT NULL DEFAULT '',
            ratings_json TEXT NOT NULL DEFAULT '{}',
            weaknesses_json TEXT NOT NULL DEFAULT '[]',
            fit_score REAL NOT NULL DEFAULT 0,
            deterministic_signals_json TEXT NOT NULL DEFAULT '{}',
            seg_start_key TEXT NOT NULL,
            seg_end_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'proposed',
            rank INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX idx_candidates_source ON candidates(source_id, fit_score DESC);
        CREATE TABLE candidate_revisions (
            id TEXT PRIMARY KEY,
            candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
            start_s REAL NOT NULL,
            end_s REAL NOT NULL,
            by TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE selections (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
            position INTEGER NOT NULL DEFAULT 0,
            preset_id TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, candidate_id)
        );
        CREATE TABLE edit_settings (
            id TEXT PRIMARY KEY,
            selection_id TEXT NOT NULL UNIQUE REFERENCES selections(id) ON DELETE CASCADE,
            framing_json TEXT NOT NULL DEFAULT '{}',
            subtitles_json TEXT NOT NULL DEFAULT '{}',
            effects_json TEXT NOT NULL DEFAULT '{}',
            audio_json TEXT NOT NULL DEFAULT '{}',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE presets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            builtin INTEGER NOT NULL DEFAULT 0,
            settings_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE export_jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            selection_id TEXT NOT NULL REFERENCES selections(id) ON DELETE CASCADE,
            output_path TEXT NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'queued',
            error TEXT,
            started_at TEXT,
            finished_at TEXT,
            ffprobe_json TEXT
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT,
            type TEXT NOT NULL,
            state TEXT NOT NULL,
            stage TEXT,
            params_json TEXT NOT NULL DEFAULT '{}',
            checkpoint_json TEXT NOT NULL DEFAULT '{}',
            error_json TEXT,
            progress_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_jobs_state ON jobs(state);
        CREATE TABLE job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            at TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL
        );
        CREATE TABLE provider_profiles (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            adapter TEXT NOT NULL,
            base_url TEXT NOT NULL,
            default_model TEXT,
            capabilities_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE model_registry (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            version TEXT,
            path TEXT NOT NULL,
            sha256 TEXT,
            bytes INTEGER,
            installed_at TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL
        );
        CREATE TABLE request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT,
            operation TEXT NOT NULL,
            approx_tokens INTEGER,
            data_categories TEXT NOT NULL,
            outcome TEXT NOT NULL
        );
        """,
    ),
    (
        2,
        """
        CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_transcripts_source ON transcripts(source_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assets_source_kind ON assets(source_id, kind, created_at);
        CREATE INDEX IF NOT EXISTS idx_candidates_run ON candidates(analysis_run_id, rank);
        CREATE INDEX IF NOT EXISTS idx_candidate_revisions_candidate ON candidate_revisions(candidate_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_selections_project ON selections(project_id, position);
        CREATE INDEX IF NOT EXISTS idx_exports_project_state ON export_jobs(project_id, state);
        CREATE INDEX IF NOT EXISTS idx_jobs_project_created ON jobs(project_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_job_events_job ON job_events(job_id, id);
        """,
    ),
]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self.conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            applied = {
                row["version"] for row in self.conn.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                self.conn.executescript(sql)
                self.conn.execute(
                    "INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",
                    (version, now()),
                )
                self.conn.commit()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """One lock and one commit for a group of related writes.

        The engine shares a single SQLite connection. Committing after every
        segment/word turned a normal transcript save into thousands of fsyncs.
        Callers must use the yielded connection directly for grouped writes.
        """
        with self._lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self.conn.executemany(sql, [tuple(r) for r in rows])
            self.conn.commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            return [dict(row) for row in cur.fetchall()]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def loads(value: str | None, default: Any = None) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
