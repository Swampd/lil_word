#!/bin/bash
cd "$(dirname "$0")"
echo "──────────────────────────────────────────────"
echo "Lil Word launcher"
echo "Working directory: $(pwd)"
echo "Python executable:"
./venv/bin/python --version
echo "Source: $(pwd)/app/main.py"
echo "Log file: $HOME/.lil_word/app.log"
echo "──────────────────────────────────────────────"
./venv/bin/python -m app.main
