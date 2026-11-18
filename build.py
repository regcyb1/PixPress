"""
Build a standalone PixPress app for the current OS.

    python build.py

Output (in dist/):
  Windows → PixPress-Windows-x64.exe       (single portable .exe)
  macOS   → PixPress-macOS-arm64.dmg       (or -x64 on Intel; drag-to-Applications disk image)
  Linux   → PixPress-Linux-x64             (single executable)
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pixpress import APP_NAME, __version__  # noqa: E402

ROOT = Path(__file__).resolve().parent
DIST, BUILD = ROOT / "dist", ROOT / "build"

COLLECT_ALL = ["gradio", "gradio_client", "safehttpx", "groovy", "httpx", "starlette",
               "fastapi", "pydantic", "pypdfium2", "pypdfium2_raw"]
# Optional heavy libraries that must not be bundled (the app works without them).
EXCLUDE = ["torch", "torchvision", "tkinter", "matplotlib", "IPython", "pytest"]


def arch() -> str:
    m = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(m, m)


def run(cmd):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


def make_dmg(app_bundle: Path, dmg: Path):
    """Disk image with the app and an Applications shortcut to drag it onto."""
    staging = BUILD / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    shutil.copytree(app_bundle, staging / app_bundle.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    dmg.unlink(missing_ok=True)
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", staging,
         "-ov", "-format", "UDZO", dmg])


def main():
    print("=" * 56)
    print(f" Building {APP_NAME} v{__version__} for {platform.system()} {arch()}")
    print("=" * 56)

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])

    for d in (BUILD, DIST):
        shutil.rmtree(d, ignore_errors=True)

    sys.path.insert(0, str(ROOT / "assets"))
    from make_icon import main as make_icons
    icons = make_icons(BUILD / "icon")

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           f"--name={APP_NAME}", f"--distpath={DIST}", f"--workpath={BUILD / 'pyinstaller'}",
           f"--specpath={BUILD}"]
    cmd += [f"--collect-all={m}" for m in COLLECT_ALL]
    cmd += [f"--exclude-module={m}" for m in EXCLUDE]

    system = platform.system()
    if system == "Windows":
        cmd += ["--onefile", f"--icon={icons / 'icon.ico'}"]
    elif system == "Darwin":
        # .app bundles must be one-folder builds; they then go into a .dmg
        cmd += ["--onedir", f"--icon={icons / 'icon.icns'}",
                "--osx-bundle-identifier=com.pixpress.app"]
    else:
        cmd += ["--onefile"]
    cmd.append(str(ROOT / "app.py"))
    run(cmd)

    if system == "Windows":
        final = DIST / f"{APP_NAME}-Windows-{arch()}.exe"
        (DIST / f"{APP_NAME}.exe").replace(final)
    elif system == "Darwin":
        final = DIST / f"{APP_NAME}-macOS-{arch()}.dmg"
        make_dmg(DIST / f"{APP_NAME}.app", final)
    else:
        final = DIST / f"{APP_NAME}-Linux-{arch()}"
        (DIST / APP_NAME).replace(final)
        os.chmod(final, 0o755)

    size_mb = final.stat().st_size / 1024 / 1024
    print("\n" + "=" * 56)
    print(f"[SUCCESS] {final.relative_to(ROOT)}  ({size_mb:.0f} MB)")
    print("=" * 56)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"\n[ERROR] Build failed: {exc}")
        sys.exit(1)
