@echo off
.\venv\Scripts\python.exe -m pytest tests/ -v
if %ERRORLEVEL% neq 0 pause
