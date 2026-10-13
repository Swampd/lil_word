"""Tests for ProjectService – including old-schema migration."""

import sqlite3
import tempfile
import os
from pathlib import Path

import pytest

from app.models.caption import Caption, TranscriptWord
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


def test_database_creates_query_indexes_idempotently(tmp_path):
    db_path = tmp_path / "indexed.db"

    svc = ProjectService(db_path)
    svc.close()
    svc = ProjectService(db_path)
    try:
        expected = {
            "idx_projects_updated_at": ["updated_at"],
            "idx_captions_project_idx": ["project_id", "idx"],
            "idx_transcript_words_project_idx": ["project_id", "idx"],
            "idx_transcript_segments_project_idx": ["project_id", "idx"],
        }
        indexes = {
            row[0]
            for row in svc._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

        assert expected.keys() <= indexes
        for index_name, columns in expected.items():
            actual_columns = [
                row[2]
                for row in svc._conn.execute(
                    f"PRAGMA index_info('{index_name}')"
                ).fetchall()
            ]
            assert actual_columns == columns
    finally:
        svc.close()


def test_save_captions_rolls_back_a_partial_replacement(tmp_path):
    db_path = tmp_path / "caption_rollback.db"
    svc = ProjectService(db_path)
    project = svc.create_project(Project(title="Caption rollback"))
    svc.save_captions(project.id, [
        Caption(0, 1000, "original one"),
        Caption(1100, 2000, "original two"),
    ])

    with pytest.raises(sqlite3.IntegrityError):
        svc.save_captions(project.id, [
            Caption(0, 500, "partial replacement"),
            Caption(600, 1000, None),
        ])

    assert svc._conn.in_transaction is False
    assert [caption.text for caption in svc.load_captions(project.id)] == [
        "original one",
        "original two",
    ]
    svc.create_project(Project(title="Later unrelated save"))
    svc.close()

    reopened = ProjectService(db_path)
    try:
        assert [caption.text for caption in reopened.load_captions(project.id)] == [
            "original one",
            "original two",
        ]
    finally:
        reopened.close()


def test_save_words_rolls_back_a_partial_replacement(tmp_path):
    db_path = tmp_path / "word_rollback.db"
    svc = ProjectService(db_path)
    project = svc.create_project(Project(title="Word rollback"))
    svc.save_words(project.id, [
        TranscriptWord(0, 200, "original", idx=0),
        TranscriptWord(250, 500, "words", idx=1),
    ])

    with pytest.raises(sqlite3.IntegrityError):
        svc.save_words(project.id, [
            TranscriptWord(0, 100, "partial", idx=0),
            TranscriptWord(150, 250, None, idx=1),
        ])

    assert svc._conn.in_transaction is False
    assert [word.text for word in svc.load_words(project.id)] == [
        "original",
        "words",
    ]
    svc.close()


def test_save_segments_rolls_back_a_partial_replacement(tmp_path):
    db_path = tmp_path / "segment_rollback.db"
    svc = ProjectService(db_path)
    project = svc.create_project(Project(title="Segment rollback"))
    svc.save_segments(project.id, [
        {"start": 0.0, "end": 1.0, "text": "original one"},
        {"start": 1.0, "end": 2.0, "text": "original two"},
    ])

    with pytest.raises(KeyError):
        svc.save_segments(project.id, [
            {"start": 0.0, "end": 0.5, "text": "partial replacement"},
            {"start": 0.5, "text": "missing end"},
        ])

    assert svc._conn.in_transaction is False
    assert svc.load_segments(project.id) == [
        {"start": 0.0, "end": 1.0, "text": "original one"},
        {"start": 1.0, "end": 2.0, "text": "original two"},
    ]
    svc.close()


def test_bulk_save_rolls_back_when_commit_fails(tmp_path):
    db_path = tmp_path / "commit_rollback.db"
    svc = ProjectService(db_path)
    svc._conn.execute("PRAGMA foreign_keys=ON")
    svc._conn.execute("PRAGMA defer_foreign_keys=ON")

    with pytest.raises(sqlite3.IntegrityError):
        svc.save_captions(999_999, [Caption(0, 1000, "orphan")])

    assert svc._conn.in_transaction is False
    count = svc._conn.execute(
        "SELECT COUNT(*) FROM captions WHERE project_id=999999"
    ).fetchone()[0]
    assert count == 0
    svc.close()


def test_migration_adds_media_fps_with_zero_default(tmp_path):
    db_path = tmp_path / "pre_fps.db"
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            media_path TEXT NOT NULL DEFAULT '',
            audio_path TEXT NOT NULL DEFAULT '',
            proxy_path TEXT NOT NULL DEFAULT '',
            media_duration_ms INTEGER NOT NULL DEFAULT 0,
            has_video INTEGER NOT NULL DEFAULT 0,
            title TEXT NOT NULL DEFAULT 'Untitled'
        )
    """)
    conn.execute(
        "INSERT INTO projects (created_at, updated_at, title) VALUES (1.0, 1.0, ?)",
        ("Legacy FPS",),
    )
    conn.commit()
    conn.close()

    svc = ProjectService(db_path)
    try:
        project = svc.get_latest_project()
        assert project is not None
        assert project.media_fps == 0
    finally:
        svc.close()


def test_project_media_fps_round_trips_through_create_and_update(tmp_path):
    svc = ProjectService(tmp_path / "fps_round_trip.db")
    try:
        project = svc.create_project(Project(title="FPS", media_fps=24))
        assert svc.load_project(project.id).media_fps == 24

        project.media_fps = 30
        svc.update_project(project)
        assert svc.load_project(project.id).media_fps == 30
    finally:
        svc.close()
