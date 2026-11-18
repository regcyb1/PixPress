@echo off
REM Double-click to launch PixPress (Windows).
REM Creates or repairs the virtual environment automatically.
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python 3 is not installed. Install it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^) and try again.
    pause
    exit /b 1
)

REM Rebuild the venv only if its Python itself is broken.
venv\Scripts\python.exe -c "import sys" >nul 2>nul
if errorlevel 1 (
    echo Creating the PixPress environment ^(first run^) - this can take a few minutes...
    if exist venv rmdir /s /q venv
    python -m venv venv || (pause & exit /b 1)
    venv\Scripts\python.exe -m pip install --upgrade pip
)

REM Install anything missing (first run, or after an update added new features).
venv\Scripts\python.exe -c "import gradio, PIL, pypdf, pypdfium2, cryptography" >nul 2>nul
if errorlevel 1 (
    echo Installing / updating PixPress dependencies...
    venv\Scripts\python.exe -m pip install -r requirements.txt || (pause & exit /b 1)
)

echo Starting PixPress - your browser will open automatically.
echo Use the "Quit app" button or close this window to stop.
venv\Scripts\python.exe app.py
pause
