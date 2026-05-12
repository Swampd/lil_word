#!/usr/bin/env bash
cd "$(dirname "$0")"
venv/bin/python -m pytest tests/ -v
if [ $? -ne 0 ]; then read -p "Press Enter to continue"; fi
