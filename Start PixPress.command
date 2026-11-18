#!/bin/bash
# Double-click to launch PixPress (macOS / Linux).
# Creates or repairs the virtual environment automatically.

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

# Rebuild the venv only if its Python itself is broken (e.g. after `brew upgrade`).
if ! venv/bin/python -c "import sys" >/dev/null 2>&1; then
    echo "Creating the PixPress environment (first run) — this can take a few minutes..."
    rm -rf venv
    "$PY_SYS" -m venv venv || { read -r -p "Failed to create venv. Press Enter to close..."; exit 1; }
    venv/bin/python -m pip install --upgrade pip
fi

# Install anything missing (first run, or after an update added new features).
if ! venv/bin/python -c "import gradio, PIL, pypdf, pypdfium2, cryptography" >/dev/null 2>&1; then
    echo "Installing / updating PixPress dependencies..."
    venv/bin/python -m pip install -r requirements.txt || { read -r -p "Install failed. Press Enter to close..."; exit 1; }
fi

echo "Starting PixPress — your browser will open automatically."
echo "Use the 'Quit app' button, close this window, or press Ctrl+C to stop."
exec venv/bin/python app.py
