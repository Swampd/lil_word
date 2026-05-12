"""Tests for ProjectService – including old-schema migration."""

import sqlite3
import tempfile
import os
from pathlib import Path

from app.models.project import Project
from app.services.project_service import ProjectService


def test_migration_adds_media_duration_ms():
    """Creating ProjectService against an old-schema DB should migrate it."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Create old-schema DB (without media_duration_ms)
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                media_path TEXT NOT NULL DEFAULT '',
                audio_path TEXT NOT NULL DEFAULT '',
                proxy_path TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT 'Untitled'
            );
            CREATE TABLE IF NOT EXISTS captions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS transcript_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 1.0
            );
        """)
        # Insert an old project to prove data survives migration
        conn.execute(
            "INSERT INTO projects (created_at, updated_at, media_path, title)"
            " VALUES (1.0, 1.0, '/old/media.mp4', 'OldProject')"
        )
        conn.commit()
        conn.close()

        # Now open with ProjectService – should migrate
        svc = ProjectService(db_path)

        # Old project should still be loadable
        old = svc.get_latest_project()
        assert old is not None
        assert old.title == "OldProject"
        assert old.media_duration_ms == 0  # default after migration

        # Should be able to create a new project with media_duration_ms
        new_proj = Project(
            title="NewProject",
            media_path="/new/media.mp4",
            media_duration_ms=20000,
        )
        new_proj = svc.create_project(new_proj)
        assert new_proj.id is not None

        # Reload and verify
        reloaded = svc.load_project(new_proj.id)
        assert reloaded.media_duration_ms == 20000

        svc.close()
    finally:
        os.unlink(db_path)


def test_fresh_db_works():
    """A fresh DB should create all tables and work without errors."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        svc = ProjectService(db_path)
        proj = Project(title="Test", media_path="/test.mp4",
                       media_duration_ms=5000, has_video=True)
        proj = svc.create_project(proj)
        assert proj.id is not None

        loaded = svc.load_project(proj.id)
        assert loaded.title == "Test"
        assert loaded.media_duration_ms == 5000
        assert loaded.has_video is True
        svc.close()
    finally:
        os.unlink(db_path)


def test_migration_adds_has_video():
    """Opening an old-schema DB (without has_video) should migrate it safely."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Create old-schema DB (has media_duration_ms but not has_video)
        conn = sqlite3.connect(db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                media_path TEXT NOT NULL DEFAULT '',
                audio_path TEXT NOT NULL DEFAULT '',
                proxy_path TEXT NOT NULL DEFAULT '',
                media_duration_ms INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT 'Untitled'
            );
            CREATE TABLE IF NOT EXISTS captions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS transcript_words (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                idx INTEGER NOT NULL,
                start_ms INTEGER NOT NULL,
                end_ms INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                confidence REAL NOT NULL DEFAULT 1.0
            );
        """)
        # Insert an old project (no has_video column)
        conn.execute(
            "INSERT INTO projects (created_at, updated_at, media_path, title)"
            " VALUES (1.0, 1.0, '/old/video.mp4', 'PreHasVideo')"
        )
        conn.commit()
        conn.close()

        # Open with ProjectService — should migrate has_video
        svc = ProjectService(db_path)

        # Old project should load with has_video defaulting to False
        old = svc.get_latest_project()
        assert old is not None
        assert old.title == "PreHasVideo"
        assert old.has_video is False

        # Should be able to create a new project with has_video=True
        new_proj = Project(
            title="WithVideo", media_path="/new/media.mp4", has_video=True,
        )
        new_proj = svc.create_project(new_proj)

        reloaded = svc.load_project(new_proj.id)
        assert reloaded.has_video is True

        svc.close()
    finally:
        os.unlink(db_path)


def test_segments_save_and_load():
    """Verify raw transcript segments can be saved and loaded."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        svc = ProjectService(db_path)
        proj = Project(title="SegmentTest")
        proj = svc.create_project(proj)

        segments = [
            {"start": 0.5, "end": 2.0, "text": "First segment"},
            {"start": 2.0, "end": 3.5, "text": "Second segment"},
        ]
        svc.save_segments(proj.id, segments)

        loaded = svc.load_segments(proj.id)
        assert len(loaded) == 2
        assert loaded[0]["start"] == 0.5
        assert loaded[0]["end"] == 2.0
        assert loaded[0]["text"] == "First segment"
        
        assert loaded[1]["start"] == 2.0
        assert loaded[1]["end"] == 3.5
        assert loaded[1]["text"] == "Second segment"

        svc.close()
    finally:
        os.unlink(db_path)


def test_migration_adds_transcript_segments():
    """Opening an older DB without transcript_segments should migrate safely."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Create old-schema DB (pre-r59)
        conn = sqlite3.connect(db_path)
        conn.executescript("""
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
            -- Intentionally omitting transcript_segments table
        """)
        conn.execute(
            "INSERT INTO projects (created_at, updated_at, title)"
            " VALUES (1.0, 1.0, 'NoSegmentsProj')"
        )
        conn.commit()
        conn.close()

        # Open with ProjectService — should run migration and create table
        svc = ProjectService(db_path)
        old = svc.get_latest_project()
        assert old is not None

        # load_segments on an old project before we save anything should return []
        # (even if the table didn't exist when we instantiated, it should exist now)
        loaded = svc.load_segments(old.id)
        assert loaded == []

        svc.close()
    finally:
        os.unlink(db_path)
