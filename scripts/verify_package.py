"""Automated smoke verification for the PyInstaller packaged artifact."""

import subprocess
import time
import sys
from pathlib import Path

def main():
    print("Verifying PyInstaller packaged artifact...")
    exe_path = Path("dist/lil_word/lil_word.exe")
    if not exe_path.exists():
        print(f"ERROR: Executable not found at {exe_path}")
        print("Did you run pyinstaller lil_word.spec first?")
        sys.exit(1)

    log_path = Path.home() / ".lil_word" / "app.log"
    if log_path.exists():
        try:
            log_path.unlink()
        except PermissionError:
            print(f"ERROR: Cannot clear {log_path}. Is the app already running?")
            sys.exit(1)

    print(f"Launching {exe_path}...")
    try:
        p = subprocess.Popen([str(exe_path)])
    except Exception as e:
        print(f"ERROR: Failed to launch executable: {e}")
        sys.exit(1)

    # Allow time for the app to boot, initialize Qt, and write to the log.
    # We use 15 seconds here because newly compiled PyInstaller executables 
    # often trigger Windows Defender scans on first launch, delaying execution.
    time.sleep(15)

    # Gracefully terminate
    p.terminate()
    try:
        p.wait(timeout=3)
    except subprocess.TimeoutExpired:
        print("WARNING: App did not terminate gracefully, forcing kill...")
        p.kill()

    if not log_path.exists():
        print("ERROR: app.log was not generated. The packaged app likely crashed before initialization.")
        sys.exit(1)

    log_content = log_path.read_text(encoding="utf-8")
    
    # Verify that the log indicates the runtime environment is the packaged executable, 
    # not the venv python.
    exe_resolved = str(exe_path.resolve())
    expected_marker = f"python executable : {exe_resolved}"
    
    if expected_marker not in log_content:
        print(f"ERROR: Expected log marker not found.")
        print(f"Expected: {expected_marker}")
        print("Log instead contains:")
        print("---")
        # Print the first few lines of the log for debugging
        print("\n".join(log_content.splitlines()[:10]))
        print("---")
        sys.exit(1)

    print("SUCCESS: Packaged app successfully booted, initialized Qt/logging, and verified its runtime path.")

if __name__ == "__main__":
    main()
