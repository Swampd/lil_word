# Lil Word

Automatic caption generator for short voiceover clips (15–30 seconds).

## Requirements

- **Python 3.12** (tested with 3.12.10)
- **ffmpeg** and **ffprobe** on PATH (tested with 8.0.1)
- GPU optional – faster-whisper uses CPU (`int8`) by default

## Setup

```powershell
# Create virtual environment
python -m venv venv

# Install dependencies
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt

# Verify
ffmpeg -version
ffprobe -version
.\venv\Scripts\python.exe -m compileall app
```

## Run

```powershell
.\venv\Scripts\python.exe -m app.main
```

## First Use

On first transcription, faster-whisper will download the `base` model (~150 MB) from Hugging Face and cache it locally. Subsequent runs reuse the cached model.

## Workflow

1. Drop a media file (or click **📂 Import**)
2. Click **🎙 Transcribe** – audio extraction, transcription, caption generation, and timing refinement happen in background threads
3. Optionally edit text, nudge timing, split/merge captions. **Split** and **Merge** explain their requirements in the status bar if they can't act (hover for tooltips). **Regen Sel** regenerates only a contiguous selection of captions using current timing rules — surrounding and unselected captions stay intact. Non-contiguous selections are rejected with a clear status message.
4. Work is autosaved to a local project database — reopen previous work via **📂 Reopen** or **📂 Recent**. A persistent "💾 Projects autosave" indicator in the bottom bar confirms this behavior.
5. Configure via toolbar:
   - **⚙️ Rules**: Caption generation rules with **named timing presets** (4 built-in: Broadcast Standard, Relaxed Reading, Fast Pacing, Tight Voiceover — plus unlimited user presets). Load a preset to try a different feel, fine-tune the knobs, save your own. If timing actually changed and transcript data is available, the app prompts to regenerate existing captions immediately or defer to the next manual Regen.
   - **🎨 Styles**: Design caption looks and save them as **named style presets** (3 built-in: Broadcast Standard, Cinema Subtitles, High Contrast — plus unlimited user presets) with a **live caption preview** that updates as you edit. Load, Save As, and Delete presets to iterate on caption looks. Style fields: font, size, text color, background color, alignment (all apply to TTML/EBU-TT/SMPTE-TT; text align only in EBU STL; text color only in MCC), caption placement (TTML-family). Note: These settings dictate the metadata written into the exported files. Final visual fidelity depends entirely on the downstream importer (e.g. Premiere Pro). Also configures Whisper model/device settings.
6. Export options:
   - **SRT**: Legacy lightweight text format
   - **ASS**: Advanced SubStation Alpha format (optimized for libass-compatible players like VLC/mpv for literal brace fidelity; use 🎬 Video hardsubs when exact rendered output matters)
   - **TTML/DFXP**: Richly formatted XML designed for Premiere Pro safe compatibility (preserves explicit regions and styles safely)
   - **EBU-TT**: EBU Tech 3350 TTML profile for European broadcast distribution (explicit styles/regions, EBU metadata)
   - **SMPTE-TT**: SMPTE ST 2052-1 TTML profile for North American broadcast and digital cinema workflows
   - **EBU STL**: EBU Tech 3264 binary teletext subtitle format for legacy European broadcast workflows
   - **MCC**: MacCaption Closed Caption format for North American broadcast CEA-608/708 caption interchange
   - **🎬 Video**: Hardcode the captions onto the source media directly (video projects only)

## Tests

```powershell
# Install dev dependencies (includes pytest)
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt

# Run tests
.\venv\Scripts\python.exe -m pytest tests/ -v
```

## Packaging (Milestone 5)

We use PyInstaller to build a standalone Windows executable. Due to upstream packaging quirks with the `webrtcvad-wheels` package on Windows, a custom hook is provided in `build_hooks/`.

Note: The packaged app requires `ffmpeg` and `ffprobe` to function. For distribution, you can simply place `ffmpeg.exe` and `ffprobe.exe` in the same directory as the packaged `lil_word.exe`, or ensure they are available on the system `PATH`.

```powershell
# Install PyInstaller
.\venv\Scripts\python.exe -m pip install pyinstaller

# Build the executable using the provided spec file
.\venv\Scripts\pyinstaller.exe -y lil_word.spec

# Run the automated smoke verification script
# This boots the packaged app and parses native logs to prove Qt and internal components initialized successfully
.\venv\Scripts\python.exe scripts\verify_package.py
```
