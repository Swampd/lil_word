#!/usr/bin/env bash
cd "$(dirname "$0")"
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
venv/bin/python -m pip install -r requirements-dev.txt
if [ $? -ne 0 ]; then read -p "Press Enter to continue"; fi
