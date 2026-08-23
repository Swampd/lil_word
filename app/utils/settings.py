"""Application settings and defaults."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path

_SETTINGS_DIR = Path(os.environ.get("APPDATA", Path.home())) / "lil_word"
_SETTINGS_FILE = _SETTINGS_DIR / "settings.json"
_LOGGER = logging.getLogger(__name__)

_DEFAULTS = {
    "whisper_model": "base",
    "whisper_device": "auto",
    "whisper_compute_type": "int8",
    "lead_in_ms": 150,
    "lead_out_ms": 250,
    "min_caption_ms": 700,
    "max_caption_ms": 3500,
    "min_gap_ms": 100,
    "target_cps_min": 12,
    "target_cps_max": 20,
    "max_lines": 2,
    "max_chars_per_line": 42,
    "export_video_codec": "libx264",
    "export_video_crf": "18",
    "export_font_family": "Arial",
    "export_font_size": "100%",
    "export_fill_color": "#FFFFFF",
    "export_background_color": "#00000000",
    "export_text_align": "center",
    "export_region_origin": "10% 80%",
    "export_region_extent": "80% 15%",
    "ebu_stl_fps": 25,
    "mcc_fps": 30,
}


class Settings:
    """Simple JSON-backed settings store."""

    def __init__(self, settings_file: str | Path | None = None):
        if settings_file:
            self._file = Path(settings_file)
            self._dir = self._file.parent
        else:
            self._file = _SETTINGS_FILE
            self._dir = _SETTINGS_DIR
        
        self._data: dict = dict(_DEFAULTS)
        self._load()

    def _load(self):
        if not self._file.exists():
            return

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                stored = json.load(f)
            if not isinstance(stored, dict):
                raise ValueError("settings root must be a JSON object")
            self._data.update(stored)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = self._file.with_name(
                f"{self._file.stem}.invalid-{timestamp}{self._file.suffix}"
            )
            suffix = 1
            while backup.exists():
                backup = self._file.with_name(
                    f"{self._file.stem}.invalid-{timestamp}-{suffix}{self._file.suffix}"
                )
                suffix += 1

            try:
                self._file.replace(backup)
                _LOGGER.error(
                    "Invalid settings file moved to %s; using defaults: %s",
                    backup,
                    exc,
                )
            except OSError:
                _LOGGER.exception(
                    "Could not back up invalid settings file %s; using defaults: %s",
                    self._file,
                    exc,
                )
        except OSError:
            _LOGGER.exception("Could not read settings file %s; using defaults", self._file)
        except Exception:
            _LOGGER.exception("Unexpected error loading settings file %s; using defaults", self._file)

    def save(self):
        self._dir.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value):
        self._data[key] = value

    # ── Style presets ────────────────────────────────────────────────────

    # Keys that make up a style preset
    _STYLE_KEYS = [
        "export_font_family", "export_font_size", "export_fill_color",
        "export_background_color", "export_text_align",
        "export_region_origin", "export_region_extent",
    ]

    def get_current_style(self) -> dict:
        """Return the current style values as a dict."""
        return {k: self.get(k, _DEFAULTS.get(k)) for k in self._STYLE_KEYS}

    def apply_style(self, style: dict):
        """Apply a style dict to the current settings (does not save)."""
        for k in self._STYLE_KEYS:
            if k in style:
                self.set(k, style[k])

    def get_style_presets(self) -> dict:
        """Return user-saved presets: {name: {style_key: value}}."""
        return dict(self._data.get("style_presets", {}))

    def save_style_preset(self, name: str, style: dict):
        """Save a named style preset (persists to disk)."""
        presets = self._data.get("style_presets", {})
        presets[name] = {k: style.get(k, _DEFAULTS.get(k)) for k in self._STYLE_KEYS}
        self._data["style_presets"] = presets
        self.save()

    def delete_style_preset(self, name: str):
        """Delete a named style preset (persists to disk)."""
        presets = self._data.get("style_presets", {})
        presets.pop(name, None)
        self._data["style_presets"] = presets
        self.save()


# Built-in presets shipped with the app (not editable by the user)
BUILTIN_PRESETS = {
    "Broadcast Standard": {
        "export_font_family": "Arial",
        "export_font_size": "100%",
        "export_fill_color": "#FFFFFF",
        "export_background_color": "#000000CC",
        "export_text_align": "center",
        "export_region_origin": "10% 80%",
        "export_region_extent": "80% 15%",
    },
    "Cinema Subtitles": {
        "export_font_family": "Helvetica Neue",
        "export_font_size": "120%",
        "export_fill_color": "#FFFFCC",
        "export_background_color": "#00000000",
        "export_text_align": "center",
        "export_region_origin": "10% 85%",
        "export_region_extent": "80% 10%",
    },
    "High Contrast": {
        "export_font_family": "Arial",
        "export_font_size": "110%",
        "export_fill_color": "#FFFF00",
        "export_background_color": "#000000FF",
        "export_text_align": "left",
        "export_region_origin": "5% 78%",
        "export_region_extent": "90% 18%",
    },
}
