@echo off
cd /d "%~dp0"
echo ──────────────────────────────────────────────
echo Lil Word launcher
echo Working directory: %cd%
echo Python executable:
.\venv\Scripts\python.exe --version
echo Source: %cd%\app\main.py
echo Log file: %USERPROFILE%\.lil_word\app.log
echo ──────────────────────────────────────────────
.\venv\Scripts\python.exe -m app.main
if %ERRORLEVEL% neq 0 (
    echo.
    echo App exited with error code %ERRORLEVEL%
    pause
)
