#!/bin/bash
# Double-click to launch Image Resizer (macOS / Linux).
# Creates or repairs the virtual environment automatically on first run.

# Resolve the real project folder, even when launched through a Desktop symlink.
SCRIPT="$0"
if command -v readlink >/dev/null 2>&1 && readlink -f "$SCRIPT" >/dev/null 2>&1; then
    SCRIPT="$(readlink -f "$SCRIPT")"
fi
cd "$(dirname "$SCRIPT")" || exit 1

PY_SYS="$(command -v python3 || command -v python)"
if [ -z "$PY_SYS" ]; then
    echo "Python 3 is not installed. Install it from https://www.python.org/downloads/ and try again."
    read -r -p "Press Enter to close..."
    exit 1
fi

# (Re)build the venv if it is missing or its Python link is broken (e.g. after `brew upgrade`).
if ! venv/bin/python -c "import gradio, PIL" >/dev/null 2>&1; then
    echo "Setting up Image Resizer (first run or repair) — this can take a few minutes..."
    rm -rf venv
    "$PY_SYS" -m venv venv || { read -r -p "Failed to create venv. Press Enter to close..."; exit 1; }
    venv/bin/python -m pip install --upgrade pip
    venv/bin/python -m pip install -r requirements.txt || { read -r -p "Install failed. Press Enter to close..."; exit 1; }
fi

echo "Starting Image Resizer — your browser will open at http://localhost:7860"
echo "Close this window (or press Ctrl+C) to stop the app."
exec venv/bin/python resize_app.py
