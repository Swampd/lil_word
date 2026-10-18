"""Failure-safety tests for the JSON-backed settings store."""

import json

import pytest

import app.utils.settings as settings_module
from app.utils.settings import Settings


def test_replace_all_keeps_memory_and_file_unchanged_when_replace_fails(
    tmp_path,
    monkeypatch,
):
    settings_path = tmp_path / "settings.json"
    settings = Settings(settings_path)
    settings.set("lead_in_ms", 175)
    settings.save()
    before_memory = settings.to_dict()
    before_file = json.loads(settings_path.read_text(encoding="utf-8"))

    def fail_replace(_source, _destination):
        raise OSError("simulated atomic replace failure")

    monkeypatch.setattr(settings_module.os, "replace", fail_replace)

    updated = settings.to_dict()
    updated["lead_in_ms"] = 900
    with pytest.raises(OSError, match="simulated atomic replace failure"):
        settings.replace_all(updated)

    assert settings.to_dict() == before_memory
    assert json.loads(settings_path.read_text(encoding="utf-8")) == before_file
    assert list(tmp_path.glob("*.tmp")) == []
