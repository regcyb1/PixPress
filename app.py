#!/usr/bin/env python3
"""
PixPress — resize images, print passport photo sheets and work with PDFs, all locally.

Run:  python app.py      (your browser opens automatically)
"""

import logging
import multiprocessing
import os
import sys
import tempfile


def _fix_windowed_streams():
    """Packaged GUI builds have no console: sys.stdout/stderr are None, which crashes
    libraries that print or log. Send that output to a log file instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_path = os.path.join(tempfile.gettempdir(), "PixPress.log")
    stream = open(log_path, "a", buffering=1, encoding="utf-8", errors="replace")
    sys.stdout = sys.stdout or stream
    sys.stderr = sys.stderr or stream


def main():
    multiprocessing.freeze_support()  # required for the bundled app's worker processes
    _fix_windowed_streams()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    from pixpress.ui import launch

    launch()


if __name__ == "__main__":
    main()
