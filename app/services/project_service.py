"""Project service – SQLite-backed project persistence."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional

from app.models.caption import Caption, TranscriptWord
from app.models.project import Project

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    media_path TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    proxy_path TEXT NOT NULL DEFAULT '',
    media_duration_ms INTEGER NOT NULL DEFAULT 0,
    has_video INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT 'Untitled'
);

CREATE TABLE IF NOT EXISTS captions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS transcript_words (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    idx INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
"""

_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_projects_updated_at
    ON projects (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_captions_project_idx
    ON captions (project_id, idx);

CREATE INDEX IF NOT EXISTS idx_transcript_words_project_idx
    ON transcript_words (project_id, idx);

CREATE INDEX IF NOT EXISTS idx_transcript_segments_project_idx
    ON transcript_segments (project_id, idx);
"""


class ProjectService:
    """Manages project persistence via SQLite."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._ensure_db()

    def _ensure_db(self):
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._ensure_indexes()
        self._conn.commit()

    def _ensure_indexes(self):
        """Create query indexes after all schema migrations are complete."""
        self._conn.executescript(_INDEXES)

    def _migrate(self):
        """Apply schema migrations for columns/tables added after initial release."""
        cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(projects)").fetchall()
        }
        if "media_duration_ms" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN media_duration_ms INTEGER NOT NULL DEFAULT 0"
            )
        if "has_video" not in cols:
            self._conn.execute(
                "ALTER TABLE projects ADD COLUMN has_video INTEGER NOT NULL DEFAULT 0"
            )

        # Migration: transcript_segments table (added r59)
        tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "transcript_segments" not in tables:
            self._conn.execute("""
                CREATE TABLE transcript_segments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL,
                    idx INTEGER NOT NULL,
                    start_s REAL NOT NULL,
                    end_s REAL NOT NULL,
                    text TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """)

    # ── Project CRUD ─────────────────────────────────────────────────────

    def create_project(self, project: Project) -> Project:
        now = time.time()
        cur = self._conn.execute(
            "INSERT INTO projects (created_at, updated_at, media_path, audio_path, proxy_path,"
            " media_duration_ms, has_video, title)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, now, project.media_path, project.audio_path, project.proxy_path,
             project.media_duration_ms, int(project.has_video), project.title),
        )
        project.id = cur.lastrowid
        project.created_at = now
        project.updated_at = now
        self._conn.commit()
        return project

    def update_project(self, project: Project):
        project.updated_at = time.time()
        self._conn.execute(
            "UPDATE projects SET updated_at=?, media_path=?, audio_path=?, proxy_path=?,"
            " media_duration_ms=?, has_video=?, title=? WHERE id=?",
            (project.updated_at, project.media_path, project.audio_path,
             project.proxy_path, project.media_duration_ms, int(project.has_video),
             project.title, project.id),
        )
        self._conn.commit()

    def load_project(self, project_id: int) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT id, created_at, updated_at, media_path, audio_path, proxy_path,"
            " media_duration_ms, has_video, title FROM projects WHERE id=?", (project_id,),
        ).fetchone()
        if not row:
            return None
        return Project(
            id=row[0], created_at=row[1], updated_at=row[2],
            media_path=row[3], audio_path=row[4], proxy_path=row[5],
            media_duration_ms=row[6], has_video=bool(row[7]), title=row[8],
        )

    def get_latest_project(self) -> Optional[Project]:
        row = self._conn.execute(
            "SELECT id FROM projects ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        if row:
            return self.load_project(row[0])
        return None

    def list_recent_projects(self, limit: int = 10) -> list[Project]:
        """Return the most recently updated projects, newest first."""
        rows = self._conn.execute(
            "SELECT id, created_at, updated_at, media_path, audio_path, proxy_path,"
            " media_duration_ms, has_video, title FROM projects ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            Project(
                id=r[0], created_at=r[1], updated_at=r[2],
                media_path=r[3], audio_path=r[4], proxy_path=r[5],
                media_duration_ms=r[6], has_video=bool(r[7]), title=r[8],
            )
            for r in rows
        ]

    # ── Captions ─────────────────────────────────────────────────────────

    def save_captions(self, project_id: int, captions: list[Caption]):
        self._conn.execute("DELETE FROM captions WHERE project_id=?", (project_id,))
        for i, cap in enumerate(captions):
            self._conn.execute(
                "INSERT INTO captions (project_id, idx, start_ms, end_ms, text)"
                " VALUES (?, ?, ?, ?, ?)",
                (project_id, i, cap.start_ms, cap.end_ms, cap.text),
            )
        self._conn.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (time.time(), project_id),
        )
        self._conn.commit()

    def load_captions(self, project_id: int) -> list[Caption]:
        rows = self._conn.execute(
            "SELECT start_ms, end_ms, text FROM captions WHERE project_id=? ORDER BY idx",
            (project_id,),
        ).fetchall()
        return [Caption(start_ms=r[0], end_ms=r[1], text=r[2]) for r in rows]

    # ── Transcript words ─────────────────────────────────────────────────

    def save_words(self, project_id: int, words: list[TranscriptWord]):
        self._conn.execute("DELETE FROM transcript_words WHERE project_id=?", (project_id,))
        for w in words:
            self._conn.execute(
                "INSERT INTO transcript_words (project_id, idx, start_ms, end_ms, text, confidence)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, w.idx, w.start_ms, w.end_ms, w.text, w.confidence),
            )
        self._conn.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (time.time(), project_id),
        )
        self._conn.commit()

    def load_words(self, project_id: int) -> list[TranscriptWord]:
        rows = self._conn.execute(
            "SELECT idx, start_ms, end_ms, text, confidence"
            " FROM transcript_words WHERE project_id=? ORDER BY idx",
            (project_id,),
        ).fetchall()
        return [
            TranscriptWord(idx=r[0], start_ms=r[1], end_ms=r[2], text=r[3], confidence=r[4])
            for r in rows
        ]

    # ── Transcript segments ───────────────────────────────────────────────

    def save_segments(self, project_id: int, segments: list[dict]):
        """Persist raw transcript segments (start/end in seconds, text)."""
        self._conn.execute(
            "DELETE FROM transcript_segments WHERE project_id=?", (project_id,)
        )
        for i, seg in enumerate(segments):
            self._conn.execute(
                "INSERT INTO transcript_segments"
                " (project_id, idx, start_s, end_s, text)"
                " VALUES (?, ?, ?, ?, ?)",
                (project_id, i, seg["start"], seg["end"], seg.get("text", "")),
            )
        self._conn.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (time.time(), project_id),
        )
        self._conn.commit()

    def load_segments(self, project_id: int) -> list[dict]:
        """Load raw transcript segments. Returns empty list for older projects."""
        # Guard: table may not exist in very old databases opened before migration
        tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "transcript_segments" not in tables:
            return []
        rows = self._conn.execute(
            "SELECT start_s, end_s, text"
            " FROM transcript_segments WHERE project_id=? ORDER BY idx",
            (project_id,),
        ).fetchall()
        return [{"start": r[0], "end": r[1], "text": r[2]} for r in rows]

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
