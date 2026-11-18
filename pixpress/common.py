"""Shared helpers: temp job folders, file handling, zipping, formatting."""

import atexit
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path

log = logging.getLogger("pixpress")

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif"}
PDF_EXTENSIONS = {".pdf"}

_ROOT = None
JOB_MAX_AGE_S = 3600  # results older than this are cleaned up on the next job


def _root() -> Path:
    """Per-process temp folder for all results; removed when the app exits."""
    global _ROOT
    if _ROOT is None:
        _ROOT = Path(tempfile.mkdtemp(prefix="pixpress_"))
        atexit.register(shutil.rmtree, _ROOT, True)
    return _ROOT


def new_job_dir(prefix: str = "job_") -> Path:
    """Create a fresh folder for one job, pruning folders from old jobs."""
    root = _root()
    now = time.time()
    for d in root.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > JOB_MAX_AGE_S:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass
    return Path(tempfile.mkdtemp(prefix=prefix, dir=root))


def file_path(f) -> Path:
    """Path of an uploaded file (Gradio gives str paths or objects with .name)."""
    if isinstance(f, (str, os.PathLike)):
        return Path(f)
    return Path(getattr(f, "name", f))


def unique_name(name: str, used: set) -> str:
    """Return `name`, or `name (2)`, `name (3)`… so it is not in `used` (case-insensitive)."""
    stem, suffix = os.path.splitext(name)
    candidate, i = name, 2
    while candidate.lower() in used:
        candidate = f"{stem} ({i}){suffix}"
        i += 1
    used.add(candidate.lower())
    return candidate


def natural_key(text: str):
    """Sort key so 'page2' comes before 'page10'."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", text)]


def make_zip(paths, zip_path) -> str:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, Path(p).name)
    return str(zip_path)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")
