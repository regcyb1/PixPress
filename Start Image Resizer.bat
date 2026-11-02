@echo off
REM Double-click to launch Image Resizer (Windows).
REM Creates or repairs the virtual environment automatically on first run.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 is not installed. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and try again.
    pause
    exit /b 1
)

venv\Scripts\python.exe -c "import gradio, PIL" >nul 2>nul
if errorlevel 1 (
    echo Setting up Image Resizer ^(first run or repair^) - this can take a few minutes...
    if exist venv rmdir /s /q venv
    python -m venv venv || (pause & exit /b 1)
    venv\Scripts\python.exe -m pip install --upgrade pip
    venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
)

echo Starting Image Resizer - your browser will open at http://localhost:7860
echo Close this window to stop the app.
venv\Scripts\python.exe resize_app.py
pause
