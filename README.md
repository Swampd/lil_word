# Lil Word

[![Tests](https://github.com/Swampd/lil_word/actions/workflows/tests.yml/badge.svg)](https://github.com/Swampd/lil_word/actions/workflows/tests.yml)

Lil Word is a local-first desktop application for transcribing audio and video into editable captions and professional subtitle formats.

> **Status:** Portfolio preview under active development. The core transcription, editing, project autosave, and export workflows are implemented and covered by an automated test suite.

## What it does

- Transcribes local media with `faster-whisper`, using CPU by default with optional GPU acceleration.
- Generates readable caption blocks from word-level timestamps and configurable timing rules.
- Provides synchronized video preview, playhead highlighting, inline text and timing edits, split/merge tools, and selected-caption regeneration.
- Autosaves projects, captions, transcript words, and user presets to a local SQLite database.
- Exports SRT, ASS, TTML/DFXP, EBU-TT, SMPTE-TT, EBU STL, MCC, and burned-in video.
- Keeps media and project data on the user's machine; only the Whisper model download requires network access.

## Technical highlights

- **Desktop UI:** Python and PySide6 with responsive background workers for media import, transcription, and export.
- **Media pipeline:** FFmpeg/ffprobe for probing, audio extraction, proxy generation, and hard-subtitle rendering.
- **Caption engine:** Configurable reading-speed, duration, line-length, and gap rules with word-level timing refinement.
- **Persistence:** SQLite project storage with schema migrations, ordered child-table indexes, and debounced autosave.
- **Interchange:** Dedicated exporters and validation for consumer, web, and broadcast caption standards.
- **Reliability:** Headless GUI, service, exporter, persistence, and acceptance coverage through pytest.

## Project structure

```text
app/
├── exporters/   Subtitle and broadcast-format writers
├── models/      Caption, project, cue, region, and style data models
├── services/    Transcription, media, persistence, alignment, and export logic
├── ui/          PySide6 windows, panels, dialogs, and background workers
├── utils/       Timecode, settings, import-session, and path helpers
└── validation/  Format- and profile-specific validation
tests/           Unit, GUI, packaging, and acceptance tests
```

## Requirements

- Python 3.12 (tested with 3.12.10)
- `ffmpeg` and `ffprobe` on `PATH` (tested with 8.0.1)
- A GPU is optional; transcription uses CPU with `int8` compute by default

## Setup

```bash
python -m venv venv

# macOS or Linux
source venv/bin/activate

# Windows PowerShell
# .\venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m app.main
```

On the first transcription, `faster-whisper` downloads the selected model (the default `base` model is approximately 150 MB) from Hugging Face and caches it locally.

## Workflow

1. Drop a media file into the application or choose **Import**.
2. Select **Transcribe** to extract audio, transcribe it, generate captions, and refine timing in background threads.
3. Edit caption text and timing, or use the nudge, split, merge, and **Regen Sel** tools.
4. Adjust caption-generation rules and named timing presets.
5. Configure visual styles and reusable style presets.
6. Export a subtitle file or render captions directly into the source video.

Work is autosaved locally. Previous projects can be reopened from **Reopen** or **Recent** without sending their contents to an external project service.

## Export formats

| Format | Intended use |
| --- | --- |
| SRT | Lightweight, widely supported subtitles |
| ASS | Styled subtitles for libass-compatible players |
| TTML/DFXP | Rich XML interchange, including Premiere-oriented workflows |
| EBU-TT | European broadcast distribution |
| SMPTE-TT | North American broadcast and digital-cinema interchange |
| EBU STL | Legacy European teletext workflows |
| MCC | CEA-608/708 broadcast-caption interchange |
| Burned video | Captions rendered directly into an MP4 |

## Tests

Install the development dependencies and run the suite:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

For a display-free environment such as CI:

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

## Windows packaging

The included PyInstaller specification builds a standalone Windows executable. A custom hook handles the upstream `webrtcvad-wheels` packaging layout.

```powershell
python -m pip install pyinstaller
pyinstaller -y lil_word.spec
python scripts\verify_package.py
```

The packaged application still requires `ffmpeg.exe` and `ffprobe.exe` beside `lil_word.exe` or on the system `PATH`.

## License

Lil Word is source-available for portfolio review and evaluation; it is not an open-source project. No open-source license is granted. See [LICENSE](LICENSE) for details.
