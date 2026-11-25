from __future__ import annotations

import json
from typing import Any

from .db import Database, now


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def camelize(value: Any) -> Any:
    if isinstance(value, dict):
        return {_camel(k): camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(v) for v in value]
    return value


def decamelize(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            snake = "".join("_" + ch.lower() if ch.isupper() else ch for ch in k)
            out[snake] = decamelize(v)
        return out
    if isinstance(value, list):
        return [decamelize(v) for v in value]
    return value


class SettingsRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.query_one("SELECT value_json FROM settings WHERE key=?", (key,))
        return _json(row["value_json"], default) if row else default

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO settings(key,value_json) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
            (key, self.db.dumps(value)),
        )

    def all(self) -> dict[str, Any]:
        return {r["key"]: _json(r["value_json"], None) for r in self.db.query("SELECT * FROM settings")}


class ProjectRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, name: str) -> dict[str, Any]:
        pid = self.db.new_id()
        ts = now()
        self.db.execute(
            "INSERT INTO projects(id,name,created_at,updated_at,last_opened_at) VALUES(?,?,?,?,?)",
            (pid, name.strip() or "Untitled project", ts, ts, ts),
        )
        return self.get(pid) or {}

    def get(self, project_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
        if not row:
            return None
        out = camelize(row)
        out["sources"] = self.sources(project_id)
        return out

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM projects ORDER BY COALESCE(last_opened_at,updated_at) DESC")
        source_counts = {
            r["project_id"]: r["c"]
            for r in self.db.query("SELECT project_id, COUNT(*) AS c FROM sources GROUP BY project_id")
        }
        selection_counts = {
            r["project_id"]: r["c"]
            for r in self.db.query("SELECT project_id, COUNT(*) AS c FROM selections GROUP BY project_id")
        }
        export_counts = {
            r["project_id"]: r["c"]
            for r in self.db.query(
                "SELECT project_id, COUNT(*) AS c FROM export_jobs WHERE state='succeeded' GROUP BY project_id"
            )
        }
        out = []
        for row in rows:
            item = camelize(row)
            item["counts"] = {
                "sources": source_counts.get(row["id"], 0),
                "selections": selection_counts.get(row["id"], 0),
                "exports": export_counts.get(row["id"], 0),
            }
            out.append(item)
        return out

    def sources(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM sources WHERE project_id=? ORDER BY created_at", (project_id,)
        )
        return [camelize(r) for r in rows]

    def touch(self, project_id: str, *, opened: bool = False) -> None:
        ts = now()
        if opened:
            self.db.execute(
                "UPDATE projects SET last_opened_at=?, updated_at=? WHERE id=?", (ts, ts, project_id)
            )
        else:
            self.db.execute("UPDATE projects SET updated_at=? WHERE id=?", (ts, project_id))

    def delete(self, project_id: str) -> None:
        self.db.execute("DELETE FROM projects WHERE id=?", (project_id,))

    def rename(self, project_id: str, name: str) -> None:
        self.db.execute(
            "UPDATE projects SET name=?, updated_at=? WHERE id=?", (name.strip() or "Untitled project", now(), project_id)
        )


class SourceRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, project_id: str, **fields: Any) -> dict[str, Any]:
        sid = self.db.new_id()
        self.db.execute(
            """INSERT INTO sources(id,project_id,kind,url,local_path,content_hash,title,channel,duration_s,
               width,height,fps,language,metadata_json,authorization_ack_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                sid,
                project_id,
                fields["kind"],
                fields.get("url"),
                fields.get("local_path"),
                fields.get("content_hash"),
                fields.get("title") or "Untitled source",
                fields.get("channel"),
                fields.get("duration_s"),
                fields.get("width"),
                fields.get("height"),
                fields.get("fps"),
                fields.get("language"),
                self.db.dumps(fields.get("metadata") or {}),
                fields.get("authorization_ack_at"),
                now(),
            ),
        )
        return self.get(sid) or {}

    def get(self, source_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM sources WHERE id=?", (source_id,))
        if not row:
            return None
        item = camelize(row)
        item["metadata"] = _json(row["metadata_json"], {})
        item.pop("metadataJson", None)
        item["transcripts"] = [
            camelize(r) for r in self.db.query(
                "SELECT id,origin,engine,model,language,word_timing,created_at FROM transcripts WHERE source_id=? ORDER BY created_at DESC",
                (source_id,),
            )
        ]
        return item

    def update(self, source_id: str, **fields: Any) -> None:
        allowed = {
            "url", "local_path", "content_hash", "title", "channel", "duration_s",
            "width", "height", "fps", "language", "authorization_ack_at",
        }
        sets, values = [], []
        for key, value in fields.items():
            if key in allowed:
                sets.append(f"{key}=?")
                values.append(value)
        if sets:
            values.append(source_id)
            self.db.execute(f"UPDATE sources SET {','.join(sets)} WHERE id=?", values)

    def set_metadata(self, source_id: str, metadata: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE sources SET metadata_json=? WHERE id=?", (self.db.dumps(metadata), source_id)
        )


class AssetRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        source_id: str,
        kind: str,
        path: str,
        *,
        start_s: float | None = None,
        end_s: float | None = None,
        bytes_: int | None = None,
        pinned: bool = False,
        meta: dict[str, Any] | None = None,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        aid = asset_id or self.db.new_id()
        self.db.execute(
            "INSERT INTO assets(id,source_id,kind,path,start_s,end_s,bytes,created_at,pinned,meta_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (aid, source_id, kind, path, start_s, end_s, bytes_, now(), 1 if pinned else 0, self.db.dumps(meta or {})),
        )
        return self.get(aid) or {}

    def get(self, asset_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM assets WHERE id=?", (asset_id,))
        if not row:
            return None
        item = camelize(row)
        item["meta"] = _json(row["meta_json"], {})
        item.pop("metaJson", None)
        return item

    def for_source(self, source_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            rows = self.db.query("SELECT * FROM assets WHERE source_id=? AND kind=? ORDER BY created_at", (source_id, kind))
        else:
            rows = self.db.query("SELECT * FROM assets WHERE source_id=? ORDER BY created_at", (source_id,))
        items = []
        for row in rows:
            item = camelize(row)
            # List results must expose the same parsed metadata as get(). Without
            # this, preview/render cache lookups silently miss and re-download.
            item["meta"] = _json(row["meta_json"], {})
            item.pop("metaJson", None)
            items.append(item)
        return items

    def delete(self, asset_id: str) -> None:
        self.db.execute("DELETE FROM assets WHERE id=?", (asset_id,))


class TranscriptRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(
        self,
        source_id: str,
        *,
        origin: str,
        engine: str,
        model: str | None,
        language: str | None,
        params: dict[str, Any],
        cache_key: str,
        word_timing: str,
        segments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        existing = self.db.query_one(
            "SELECT id FROM transcripts WHERE source_id=? AND cache_key=?", (source_id, cache_key)
        )
        if existing:
            return self.get(existing["id"]) or {}
        tid = self.db.new_id()
        segment_rows: list[tuple[Any, ...]] = []
        word_rows: list[tuple[Any, ...]] = []
        for seg in segments:
            seg_id = self.db.new_id()
            segment_rows.append(
                (seg_id, tid, seg["seq"], seg["seg_key"], seg["start_s"], seg["end_s"], seg["text"])
            )
            for w in seg.get("words") or []:
                word_rows.append(
                    (self.db.new_id(), seg_id, w["seq"], w["start_s"], w["end_s"], w["text"], w.get("confidence"))
                )
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO transcripts(id,source_id,origin,engine,model,language,params_json,cache_key,word_timing,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (tid, source_id, origin, engine, model, language, self.db.dumps(params), cache_key, word_timing, now()),
            )
            if segment_rows:
                conn.executemany(
                    "INSERT INTO segments(id,transcript_id,seq,seg_key,start_s,end_s,text) VALUES(?,?,?,?,?,?,?)",
                    segment_rows,
                )
            if word_rows:
                conn.executemany(
                    "INSERT INTO words(id,segment_id,seq,start_s,end_s,text,confidence) VALUES(?,?,?,?,?,?,?)",
                    word_rows,
                )
        return self.get(tid) or {}

    def get(self, transcript_id: str, *, include_words: bool = True) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM transcripts WHERE id=?", (transcript_id,))
        if not row:
            return None
        item = camelize(row)
        item["params"] = _json(row["params_json"], {})
        item.pop("paramsJson", None)
        # One join instead of one words query per segment. A 300-segment
        # transcript used to issue 300 serialized SQLite queries while holding
        # the database lock; this returns the same shape in one pass.
        if include_words:
            rows = self.db.query(
                """SELECT s.id AS s_id, s.seq AS s_seq, s.seg_key AS s_seg_key, s.start_s AS s_start_s,
                          s.end_s AS s_end_s, s.text AS s_text,
                          w.id AS w_id, w.seq AS w_seq, w.start_s AS w_start_s, w.end_s AS w_end_s,
                          w.text AS w_text, w.confidence AS w_confidence
                   FROM segments s
                   LEFT JOIN words w ON w.segment_id = s.id
                   WHERE s.transcript_id = ?
                   ORDER BY s.seq, w.seq""",
                (transcript_id,),
            )
        else:
            rows = self.db.query(
                """SELECT id AS s_id, seq AS s_seq, seg_key AS s_seg_key, start_s AS s_start_s,
                          end_s AS s_end_s, text AS s_text
                   FROM segments WHERE transcript_id=? ORDER BY seq""",
                (transcript_id,),
            )
        segments: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for r in rows:
            if current is None or current["id"] != r["s_id"]:
                current = {
                    "id": r["s_id"],
                    "seq": r["s_seq"],
                    "segKey": r["s_seg_key"],
                    "startS": r["s_start_s"],
                    "endS": r["s_end_s"],
                    "text": r["s_text"],
                    "words": [],
                }
                segments.append(current)
            if include_words and r["w_id"]:
                current["words"].append(
                    {
                        "id": r["w_id"],
                        "segmentId": r["s_id"],
                        "seq": r["w_seq"],
                        "startS": r["w_start_s"],
                        "endS": r["w_end_s"],
                        "text": r["w_text"],
                        "confidence": r["w_confidence"],
                    }
                )
        item["segments"] = segments
        return item

    def latest_for_source(self, source_id: str, *, include_words: bool = True) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT id FROM transcripts WHERE source_id=? ORDER BY created_at DESC LIMIT 1", (source_id,)
        )
        return self.get(row["id"], include_words=include_words) if row else None

    def find_cached(self, source_id: str, cache_key: str, *, include_words: bool = True) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT id FROM transcripts WHERE source_id=? AND cache_key=?", (source_id, cache_key)
        )
        return self.get(row["id"], include_words=include_words) if row else None


class CandidateRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def clear_for_run(self, analysis_run_id: str) -> None:
        self.db.execute("DELETE FROM candidates WHERE analysis_run_id=?", (analysis_run_id,))

    def insert(self, source_id: str, run_id: str, data: dict[str, Any]) -> str:
        cid = self.db.new_id()
        self.db.execute(
            """INSERT INTO candidates(id,source_id,analysis_run_id,category,categories_json,start_s,end_s,title,excerpt,
               rationale,ratings_json,weaknesses_json,fit_score,deterministic_signals_json,seg_start_key,seg_end_key,
               status,rank,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                cid, source_id, run_id, data["category"], self.db.dumps(data.get("categories") or [data["category"]]),
                data["start_s"], data["end_s"], data["title"], data.get("excerpt", ""), data.get("rationale", ""),
                self.db.dumps(data.get("ratings") or {}), self.db.dumps(data.get("weaknesses") or []),
                data.get("fit_score", 0), self.db.dumps(data.get("signals") or {}), data["seg_start_key"],
                data["seg_end_key"], "proposed", data.get("rank"), now(),
            ),
        )
        return cid

    def _decorate(self, row: dict[str, Any], revisions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        item = camelize(row)
        item["categories"] = _json(row["categories_json"], [row["category"]])
        item["ratings"] = _json(row["ratings_json"], {})
        item["weaknesses"] = _json(row["weaknesses_json"], [])
        item["signals"] = _json(row["deterministic_signals_json"], {})
        for key in ("categoriesJson", "ratingsJson", "weaknessesJson", "deterministicSignalsJson"):
            item.pop(key, None)
        item["durationS"] = round(row["end_s"] - row["start_s"], 3)
        if revisions is None:
            revisions = self.db.query(
                "SELECT start_s,end_s,by,created_at FROM candidate_revisions WHERE candidate_id=? ORDER BY created_at",
                (row["id"],),
            )
        item["revisions"] = [camelize(r) for r in revisions]
        return item

    def list(self, source_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id:
            rows = self.db.query(
                "SELECT * FROM candidates WHERE source_id=? AND analysis_run_id=? ORDER BY COALESCE(rank,999), fit_score DESC",
                (source_id, run_id),
            )
        else:
            latest = self.db.query_one(
                "SELECT id FROM analysis_runs WHERE source_id=? ORDER BY started_at DESC LIMIT 1", (source_id,)
            )
            rows = self.db.query(
                "SELECT * FROM candidates WHERE source_id=? AND analysis_run_id=? ORDER BY COALESCE(rank,999), fit_score DESC",
                (source_id, latest["id"] if latest else ""),
            )
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        revision_rows = self.db.query(
            f"""SELECT candidate_id,start_s,end_s,by,created_at FROM candidate_revisions
                WHERE candidate_id IN ({placeholders}) ORDER BY created_at""",
            ids,
        )
        by_candidate: dict[str, list[dict[str, Any]]] = {cid: [] for cid in ids}
        for revision in revision_rows:
            by_candidate[revision["candidate_id"]].append(revision)
        return [self._decorate(r, by_candidate.get(r["id"], [])) for r in rows]

    def get(self, candidate_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM candidates WHERE id=?", (candidate_id,))
        return self._decorate(row) if row else None

    def update_bounds(self, candidate_id: str, start_s: float, end_s: float, by: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM candidates WHERE id=?", (candidate_id,))
        if not row:
            return None
        self.db.execute(
            "INSERT INTO candidate_revisions(id,candidate_id,start_s,end_s,by,created_at) VALUES(?,?,?,?,?,?)",
            (self.db.new_id(), candidate_id, row["start_s"], row["end_s"], by, now()),
        )
        self.db.execute(
            "UPDATE candidates SET start_s=?,end_s=?,status='edited' WHERE id=?", (start_s, end_s, candidate_id)
        )
        return self.get(candidate_id)

    def revisions(self, candidate_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM candidate_revisions WHERE candidate_id=? ORDER BY created_at DESC, rowid DESC",
            (candidate_id,),
        )
        return [camelize(r) for r in rows]

    def undo(self, candidate_id: str) -> dict[str, Any] | None:
        latest = self.db.query_one(
            "SELECT * FROM candidate_revisions WHERE candidate_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (candidate_id,),
        )
        if not latest:
            return None
        self.db.execute("DELETE FROM candidate_revisions WHERE id=?", (latest["id"],))
        self.db.execute(
            "UPDATE candidates SET start_s=?,end_s=?,status='edited' WHERE id=?",
            (latest["start_s"], latest["end_s"], candidate_id),
        )
        return self.get(candidate_id)

    def rename(self, candidate_id: str, title: str) -> None:
        self.db.execute("UPDATE candidates SET title=? WHERE id=?", (title.strip()[:140], candidate_id))

    def set_status(self, candidate_id: str, status: str) -> None:
        self.db.execute("UPDATE candidates SET status=? WHERE id=?", (status, candidate_id))

    def update_rank_and_score(self, candidate_id: str, rank: int, score: float) -> None:
        self.db.execute("UPDATE candidates SET rank=?, fit_score=? WHERE id=?", (rank, score, candidate_id))

    def add_category(self, candidate_id: str, category: str) -> None:
        row = self.db.query_one("SELECT categories_json FROM candidates WHERE id=?", (candidate_id,))
        if not row:
            return
        cats = _json(row["categories_json"], [])
        if category not in cats:
            cats.append(category)
            self.db.execute(
                "UPDATE candidates SET categories_json=? WHERE id=?", (self.db.dumps(cats), candidate_id)
            )


class SelectionRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def set(self, project_id: str, candidate_ids: list[str], preset_id: str | None) -> list[dict[str, Any]]:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM selections WHERE project_id=?", (project_id,))
            for position, cid in enumerate(candidate_ids):
                sid = self.db.new_id()
                conn.execute(
                    "INSERT INTO selections(id,project_id,candidate_id,position,preset_id,created_at) VALUES(?,?,?,?,?,?)",
                    (sid, project_id, cid, position, preset_id, now()),
                )
                conn.execute(
                    "INSERT INTO edit_settings(id,selection_id,updated_at) VALUES(?,?,?)",
                    (self.db.new_id(), sid, now()),
                )
        return self.list(project_id)

    def list(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM selections WHERE project_id=? ORDER BY position", (project_id,))
        return [camelize(r) for r in rows]

    def get(self, selection_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM selections WHERE id=?", (selection_id,))
        return camelize(row) if row else None


DEFAULT_EDIT = {
    "framing": {
        "layout": "fill",
        "faceTracking": False,
        "zoom": 1.0,
        "manual": None,
    },
    "subtitles": {
        "enabled": True,
        "mode": "word_highlight",
        "font": "Bebas Neue",
        "fontSize": 64,
        "color": "#FFFFFF",
        "highlightColor": "#E8C77B",
        "outlineColor": "#0B0910",
        "outline": 4,
        "shadow": 1,
        "background": False,
        "position": "lower_third",
        "maxLines": 2,
        "uppercase": True,
        "hideFillers": False,
    },
    "effects": {
        "enabled": False,
        "fade": True,
        "progressBar": False,
        "cinematic": False,
        "zoomPunch": False,
    },
    "audio": {
        "loudnessTarget": -14.0,
        "truePeak": -1.5,
        "denoise": False,
        "voiceEnhance": False,
        "musicPath": None,
        "musicGainDb": -18.0,
        "ducking": True,
    },
    "metadata": {"title": "", "description": "", "hashtags": []},
}


class EditRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, selection_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM edit_settings WHERE selection_id=?", (selection_id,))
        if not row:
            return {k: json.loads(json.dumps(v)) for k, v in DEFAULT_EDIT.items()}
        merged = {k: json.loads(json.dumps(v)) for k, v in DEFAULT_EDIT.items()}
        for key in ("framing", "subtitles", "effects", "audio", "metadata"):
            merged[key].update(_json(row[f"{key}_json"], {}))
        return merged

    def set(self, selection_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        current = self.get(selection_id)
        for key in ("framing", "subtitles", "effects", "audio", "metadata"):
            if key in settings and isinstance(settings[key], dict):
                current[key].update(settings[key])
        self.db.execute(
            """UPDATE edit_settings SET framing_json=?,subtitles_json=?,effects_json=?,audio_json=?,metadata_json=?,updated_at=?
               WHERE selection_id=?""",
            (
                self.db.dumps(current["framing"]),
                self.db.dumps(current["subtitles"]),
                self.db.dumps(current["effects"]),
                self.db.dumps(current["audio"]),
                self.db.dumps(current["metadata"]),
                now(),
                selection_id,
            ),
        )
        return self.get(selection_id)


class PresetRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def seed(self, builtins: list[dict[str, Any]]) -> None:
        for preset in builtins:
            existing = self.db.query_one("SELECT id FROM presets WHERE id=?", (preset["id"],))
            if existing:
                continue
            self.db.execute(
                "INSERT INTO presets(id,name,builtin,settings_json,created_at) VALUES(?,?,?,?,?)",
                (preset["id"], preset["name"], 1, self.db.dumps(preset["settings"]), now()),
            )

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM presets ORDER BY builtin DESC, name")
        out = []
        for row in rows:
            item = camelize(row)
            item["settings"] = _json(row["settings_json"], {})
            item.pop("settingsJson", None)
            out.append(item)
        return out

    def save(self, name: str, settings: dict[str, Any], preset_id: str | None = None) -> dict[str, Any]:
        pid = preset_id or self.db.new_id()
        existing = self.db.query_one("SELECT builtin FROM presets WHERE id=?", (pid,))
        if existing and existing["builtin"]:
            raise ValueError("Built-in presets cannot be overwritten; save a copy.")
        if existing:
            self.db.execute(
                "UPDATE presets SET name=?,settings_json=? WHERE id=?", (name, self.db.dumps(settings), pid)
            )
        else:
            self.db.execute(
                "INSERT INTO presets(id,name,builtin,settings_json,created_at) VALUES(?,?,0,?,?)",
                (pid, name, self.db.dumps(settings), now()),
            )
        return next(p for p in self.list() if p["id"] == pid)

    def delete(self, preset_id: str) -> None:
        self.db.execute("DELETE FROM presets WHERE id=? AND builtin=0", (preset_id,))


class ProviderRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM provider_profiles ORDER BY created_at")
        out = []
        for row in rows:
            item = camelize(row)
            item["capabilities"] = camelize(_json(row["capabilities_json"], {}))
            item["enabled"] = bool(row["enabled"])
            item.pop("capabilitiesJson", None)
            out.append(item)
        return out

    def get(self, profile_id: str) -> dict[str, Any] | None:
        return next((p for p in self.list() if p["id"] == profile_id), None)

    def save(self, data: dict[str, Any]) -> dict[str, Any]:
        pid = data.get("id") or self.db.new_id()
        existing = self.db.query_one("SELECT id FROM provider_profiles WHERE id=?", (pid,))
        caps = self.db.dumps(camelize(data.get("capabilities") or {}))
        if existing:
            self.db.execute(
                "UPDATE provider_profiles SET name=?,adapter=?,base_url=?,default_model=?,capabilities_json=?,enabled=? WHERE id=?",
                (data["name"], data["adapter"], data["base_url"], data.get("default_model"), caps, 1 if data.get("enabled", True) else 0, pid),
            )
        else:
            self.db.execute(
                "INSERT INTO provider_profiles(id,name,adapter,base_url,default_model,capabilities_json,enabled,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (pid, data["name"], data["adapter"], data["base_url"], data.get("default_model"), caps, 1 if data.get("enabled", True) else 0, now()),
            )
        return self.get(pid) or {}

    def delete(self, profile_id: str) -> None:
        self.db.execute("DELETE FROM provider_profiles WHERE id=?", (profile_id,))

    def set_capabilities(self, profile_id: str, caps: dict[str, Any]) -> None:
        self.db.execute(
            "UPDATE provider_profiles SET capabilities_json=? WHERE id=?", (self.db.dumps(camelize(caps)), profile_id)
        )


class RequestLogRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, provider: str, model: str | None, operation: str, approx_tokens: int, categories: list[str], outcome: str) -> None:
        self.db.execute(
            "INSERT INTO request_log(at,provider,model,operation,approx_tokens,data_categories,outcome) VALUES(?,?,?,?,?,?,?)",
            (now(), provider, model, operation, approx_tokens, self.db.dumps(categories), outcome),
        )
        self.db.execute(
            "DELETE FROM request_log WHERE id NOT IN (SELECT id FROM request_log ORDER BY id DESC LIMIT 500)"
        )

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM request_log ORDER BY id DESC LIMIT 200")
        out = []
        for row in rows:
            item = camelize(row)
            item["dataCategories"] = _json(row["data_categories"], [])
            item.pop("dataCategories", None) if False else None
            out.append(item)
        return out

    def clear(self) -> None:
        self.db.execute("DELETE FROM request_log")


class JobRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, job_id: str, job_type: str, params: dict[str, Any], project_id: str | None) -> None:
        ts = now()
        self.db.execute(
            "INSERT INTO jobs(id,project_id,type,state,stage,params_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (job_id, project_id, job_type, "queued", "queued", self.db.dumps(params), ts, ts),
        )

    def update(
        self,
        job_id: str,
        *,
        state: str | None = None,
        stage: str | None = None,
        checkpoint: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
    ) -> None:
        sets, values = ["updated_at=?"], [now()]
        if state is not None:
            sets.append("state=?")
            values.append(state)
        if stage is not None:
            sets.append("stage=?")
            values.append(stage)
        if checkpoint is not None:
            sets.append("checkpoint_json=?")
            values.append(self.db.dumps(checkpoint))
        if error is not None:
            sets.append("error_json=?")
            values.append(self.db.dumps(error))
        if progress is not None:
            sets.append("progress_json=?")
            values.append(self.db.dumps(progress))
        values.append(job_id)
        self.db.execute(f"UPDATE jobs SET {','.join(sets)} WHERE id=?", values)

    @staticmethod
    def _decorate(row: dict[str, Any]) -> dict[str, Any]:
        item = camelize(row)
        item["params"] = _json(row["params_json"], {})
        item["checkpoint"] = _json(row["checkpoint_json"], {})
        item["error"] = _json(row["error_json"], None)
        item["progress"] = _json(row["progress_json"], {})
        for key in ("paramsJson", "checkpointJson", "errorJson", "progressJson"):
            item.pop(key, None)
        return item

    def get(self, job_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        return self._decorate(row) if row else None

    def list(self, project_id: str | None = None, active_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        clauses, params = [], []
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        if active_only:
            clauses.append("state IN ('queued','running','paused','waiting_rate_limit','cancelling','interrupted')")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT 100"
        return [self._decorate(r) for r in self.db.query(sql, params)]

    def recover_interrupted(self) -> int:
        cur = self.db.execute(
            "UPDATE jobs SET state='interrupted', updated_at=? WHERE state IN ('running','queued','waiting_rate_limit','cancelling')",
            (now(),),
        )
        return cur.rowcount

    def add_event(self, job_id: str, level: str, message: str) -> None:
        self.db.execute(
            "INSERT INTO job_events(job_id,at,level,message) VALUES(?,?,?,?)", (job_id, now(), level, message)
        )
        self.db.execute(
            "DELETE FROM job_events WHERE job_id=? AND id NOT IN (SELECT id FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 200)",
            (job_id, job_id),
        )

    def events(self, job_id: str) -> list[dict[str, Any]]:
        return [camelize(r) for r in self.db.query("SELECT * FROM job_events WHERE job_id=? ORDER BY id", (job_id,))]


class ModelRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def upsert(self, kind: str, name: str, path: str, *, version: str | None = None, sha256: str | None = None, bytes_: int | None = None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        existing = self.db.query_one("SELECT id FROM model_registry WHERE kind=? AND name=?", (kind, name))
        if existing:
            self.db.execute(
                "UPDATE model_registry SET path=?,version=?,sha256=?,bytes=?,installed_at=?,meta_json=? WHERE id=?",
                (path, version, sha256, bytes_, now(), self.db.dumps(meta or {}), existing["id"]),
            )
            mid = existing["id"]
        else:
            mid = self.db.new_id()
            self.db.execute(
                "INSERT INTO model_registry(id,kind,name,version,path,sha256,bytes,installed_at,meta_json) VALUES(?,?,?,?,?,?,?,?,?)",
                (mid, kind, name, version, path, sha256, bytes_, now(), self.db.dumps(meta or {})),
            )
        return self.get(mid) or {}

    def get(self, model_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM model_registry WHERE id=?", (model_id,))
        if not row:
            return None
        item = camelize(row)
        item["meta"] = _json(row["meta_json"], {})
        item.pop("metaJson", None)
        return item

    def find(self, kind: str, name: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT id FROM model_registry WHERE kind=? AND name=?", (kind, name))
        return self.get(row["id"]) if row else None

    def list(self) -> list[dict[str, Any]]:
        return [self.get(r["id"]) or {} for r in self.db.query("SELECT id FROM model_registry ORDER BY kind,name")]

    def delete(self, model_id: str) -> None:
        self.db.execute("DELETE FROM model_registry WHERE id=?", (model_id,))


class AnalysisRunRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(
        self,
        source_id: str,
        transcript_id: str,
        provider_profile_id: str | None,
        model: str | None,
        params: dict[str, Any],
        prompt_version: str,
    ) -> dict[str, Any]:
        rid = self.db.new_id()
        self.db.execute(
            """INSERT INTO analysis_runs(id,source_id,transcript_id,provider_profile_id,model,params_json,
               prompt_version,started_at,state) VALUES(?,?,?,?,?,?,?,?, 'running')""",
            (rid, source_id, transcript_id, provider_profile_id, model, self.db.dumps(params), prompt_version, now()),
        )
        return self.get(rid) or {}

    def get(self, run_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM analysis_runs WHERE id=?", (run_id,))
        if not row:
            return None
        item = camelize(row)
        item["params"] = _json(row["params_json"], {})
        item["tokenUsage"] = _json(row["token_usage_json"], {})
        item["error"] = _json(row["error_json"], None)
        for key in ("paramsJson", "tokenUsageJson", "errorJson"):
            item.pop(key, None)
        return item

    def list(self, source_id: str) -> list[dict[str, Any]]:
        return [
            self.get(r["id"]) or {}
            for r in self.db.query("SELECT id FROM analysis_runs WHERE source_id=? ORDER BY started_at DESC", (source_id,))
        ]

    def finish(
        self,
        run_id: str,
        *,
        state: str,
        token_usage: dict[str, Any],
        error: dict[str, Any] | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE analysis_runs SET state=?,finished_at=?,token_usage_json=?,error_json=? WHERE id=?",
            (state, now(), self.db.dumps(token_usage), self.db.dumps(error) if error else None, run_id),
        )


class ExportJobRepo:
    def __init__(self, db: Database) -> None:
        self.db = db

    def create(self, project_id: str, selection_id: str, output_path: str, settings: dict[str, Any]) -> str:
        eid = self.db.new_id()
        self.db.execute(
            "INSERT INTO export_jobs(id,project_id,selection_id,output_path,settings_json,state,started_at) VALUES(?,?,?,?,?,?,?)",
            (eid, project_id, selection_id, output_path, self.db.dumps(settings), "running", now()),
        )
        return eid

    def finish(self, export_id: str, *, state: str, error: str | None = None, ffprobe: dict[str, Any] | None = None) -> None:
        self.db.execute(
            "UPDATE export_jobs SET state=?,error=?,ffprobe_json=?,finished_at=? WHERE id=?",
            (state, error, self.db.dumps(ffprobe) if ffprobe else None, now(), export_id),
        )

    def list(self, project_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM export_jobs WHERE project_id=? ORDER BY started_at DESC", (project_id,))
        out = []
        for row in rows:
            item = camelize(row)
            item["ffprobe"] = _json(row["ffprobe_json"], None)
            item["settings"] = _json(row["settings_json"], {})
            for key in ("ffprobeJson", "settingsJson"):
                item.pop(key, None)
            out.append(item)
        return out
