"""Image loading helpers and the bulk resize engine."""

import os
import struct
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

from .common import IMAGE_EXTENSIONS, file_path, log, make_zip, new_job_dir, stamp, unique_name

ImageFile.LOAD_TRUNCATED_IMAGES = True  # handle slightly corrupt files

try:
    import pyvips  # optional, much faster for big batches

    USE_PYVIPS = True
except (ImportError, OSError):
    pyvips = None
    USE_PYVIPS = False

CPU_DEVICE = "CPU (Pillow/pyvips)"
MAX_WORKERS = min(os.cpu_count() or 4, 16)

PRESET_RESOLUTIONS = {
    "512 × 512": (512, 512),
    "1024 × 1024": (1024, 1024),
    "2048 × 2048": (2048, 2048),
    "4096 × 4096": (4096, 4096),
    "Custom": None,
}

PRESET_PPI = {"72": 72, "150": 150, "300": 300, "Custom": None}

# UI label → (Pillow format, file extension)
OUTPUT_FORMATS = {
    "JPG": ("JPEG", ".jpg"),
    "PNG": ("PNG", ".png"),
    "WebP": ("WEBP", ".webp"),
}


@lru_cache(maxsize=1)
def detect_devices() -> tuple:
    """Compute devices available for resizing. PyTorch is optional and imported lazily
    so that worker processes and the standalone app don't pay for it."""
    devices = [CPU_DEVICE]
    try:
        import torch
    except ImportError:
        return tuple(devices)
    devices.append("CPU (PyTorch)")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            devices.append(f"CUDA:{i} – {torch.cuda.get_device_name(i)}")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("Apple MPS (Metal)")
    return tuple(devices)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------
def _has_alpha(img: Image.Image) -> bool:
    return img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)


def to_rgb(img: Image.Image) -> Image.Image:
    """Convert to RGB, flattening transparency onto white."""
    if _has_alpha(img):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img if img.mode == "RGB" else img.convert("RGB")


def open_rgb(path) -> Image.Image:
    """Open an image, apply EXIF orientation and return it as RGB."""
    img = Image.open(str(path))
    img = ImageOps.exif_transpose(img) or img
    return to_rgb(img)


def open_for_format(path, fmt: str) -> Image.Image:
    """Open an image ready to save as `fmt`: JPEG gets RGB, PNG/WebP keep transparency."""
    img = Image.open(str(path))
    img = ImageOps.exif_transpose(img) or img
    if fmt == "JPEG":
        return to_rgb(img)
    if _has_alpha(img):
        return img.convert("RGBA")
    return img if img.mode == "RGB" else img.convert("RGB")


# ---------------------------------------------------------------------------
# Saving (with optional max file size)
# ---------------------------------------------------------------------------
def _encode(img: Image.Image, fmt: str, quality: int, ppi: int) -> bytes:
    buf = BytesIO()
    if fmt == "JPEG":
        img.save(buf, "JPEG", quality=quality, optimize=True, progressive=True, dpi=(ppi, ppi))
    elif fmt == "WEBP":
        img.save(buf, "WEBP", quality=quality, method=4)
    else:
        img.save(buf, "PNG", optimize=True, dpi=(ppi, ppi))
    return buf.getvalue()


def _encode_under(img, fmt, max_quality, ppi, limit):
    """Highest quality encoding that fits in `limit` bytes; downscales if it must."""
    work = img
    smallest = None
    for step in range(12):
        low = _encode(work, fmt, 10, ppi)
        if len(low) <= limit:
            best, lo, hi = low, 11, max_quality
            while lo <= hi:
                mid = (lo + hi) // 2
                data = _encode(work, fmt, mid, ppi)
                if len(data) <= limit:
                    best, lo = data, mid + 1
                else:
                    hi = mid - 1
            note = None if step == 0 else f"shrunk to {work.width}×{work.height} px to fit"
            return best, note
        smallest = low
        if min(work.size) <= 64:
            break
        work = work.resize((max(1, int(work.width * 0.8)), max(1, int(work.height * 0.8))), Image.LANCZOS)
    return smallest, f"could not reach {limit // 1024} KB (got {len(smallest) // 1024} KB)"


def save_image(img, dst, fmt, quality, ppi, max_kb=0):
    """Save `img` to `dst`. Returns a short note when something noteworthy happened."""
    note = None
    if max_kb and fmt in ("JPEG", "WEBP"):
        data, note = _encode_under(img, fmt, quality, ppi, int(max_kb * 1024))
    else:
        data = _encode(img, fmt, quality, ppi)
        if max_kb and len(data) > max_kb * 1024:
            note = "PNG is lossless – size limit not applied"
    Path(dst).write_bytes(data)
    return note


# ---------------------------------------------------------------------------
# Resize backends (run in worker processes)
# ---------------------------------------------------------------------------
def _resize_single_image(src, dst, w, h, maintain_aspect, ppi, quality, use_pyvips,
                         device=CPU_DEVICE, fmt="JPEG", max_kb=0) -> dict:
    """Resize one image file. Returns dict(ok, src, dst, error, note)."""
    try:
        if device != CPU_DEVICE:
            note = _resize_torch(src, dst, w, h, maintain_aspect, ppi, quality, device, fmt, max_kb)
        elif use_pyvips and fmt == "JPEG" and not max_kb:
            note = _resize_pyvips(src, dst, w, h, maintain_aspect, ppi, quality)
        else:
            note = _resize_pillow(src, dst, w, h, maintain_aspect, ppi, quality, fmt, max_kb)
        return {"ok": True, "src": str(src), "dst": str(dst), "error": None, "note": note}
    except Exception as exc:
        return {"ok": False, "src": str(src), "dst": str(dst), "error": str(exc), "note": None}


def _resize_pillow(src, dst, w, h, maintain_aspect, ppi, quality, fmt, max_kb):
    img = open_for_format(src, fmt)
    if maintain_aspect:
        img.thumbnail((w, h), Image.LANCZOS)
    else:
        img = img.resize((w, h), Image.LANCZOS)
    return save_image(img, dst, fmt, quality, ppi, max_kb)


def _resize_pyvips(src, dst, w, h, maintain_aspect, ppi, quality):
    img = pyvips.Image.new_from_file(str(src), access="sequential").autorot()
    if maintain_aspect:
        img = img.resize(min(w / img.width, h / img.height))
    else:
        img = img.resize(w / img.width, vscale=h / img.height)
    if img.hasalpha():
        img = img.flatten(background=[255, 255, 255])
    if img.interpretation != "srgb":
        img = img.colourspace("srgb")
    img = img.copy(xres=ppi / 25.4, yres=ppi / 25.4)  # pixels per mm
    img.jpegsave(str(dst), Q=quality, optimize_coding=True, interlace=True, strip=True)
    _patch_jpeg_dpi(str(dst), ppi)
    return None


def _patch_jpeg_dpi(filepath: str, ppi: int):
    """Make sure the JFIF header carries the DPI (best effort)."""
    try:
        with open(filepath, "r+b") as f:
            data = f.read(16)
            if data[0:4] == b"\xff\xd8\xff\xe0" and data[6:11] == b"JFIF\x00":
                f.seek(13)
                f.write(b"\x01" + struct.pack(">HH", ppi, ppi))
    except Exception:
        pass


def _resize_torch(src, dst, w, h, maintain_aspect, ppi, quality, device_label, fmt, max_kb):
    import numpy as np
    import torch
    import torch.nn.functional as F

    if "CUDA" in device_label:
        dev = "cuda:" + device_label.split(":")[1].split(" ")[0]
    elif "MPS" in device_label:
        dev = "mps"
    else:
        dev = "cpu"

    img = open_for_format(src, fmt)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if maintain_aspect:
        scale = min(w / img.width, h / img.height)
        new_w, new_h = max(1, int(img.width * scale)), max(1, int(img.height * scale))
    else:
        new_w, new_h = w, h

    arr = np.asarray(img, dtype=np.float32) / 255.0
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(dev)
    try:
        resized = F.interpolate(tensor, size=(new_h, new_w), mode="bilinear",
                                align_corners=False, antialias=True)
    except (RuntimeError, NotImplementedError):  # antialias unsupported on some backends
        resized = F.interpolate(tensor, size=(new_h, new_w), mode="bilinear", align_corners=False)
    out = resized.squeeze(0).permute(1, 2, 0).cpu().clamp(0, 1).numpy()
    result = Image.fromarray((out * 255).round().astype(np.uint8), img.mode)
    return save_image(result, dst, fmt, quality, ppi, max_kb)


# ---------------------------------------------------------------------------
# Batch orchestrator
# ---------------------------------------------------------------------------
def process_images(files, resolution_preset, custom_width, custom_height, maintain_aspect,
                   ppi_preset, custom_ppi, quality, device=CPU_DEVICE, progress=None,
                   output_format="JPG", max_kb=0):
    """Resize uploaded files. Returns (output_path, status_markdown)."""
    if not files:
        return None, "⚠️ No files uploaded."

    if resolution_preset == "Custom":
        w, h = int(custom_width or 0), int(custom_height or 0)
    else:
        w, h = PRESET_RESOLUTIONS[resolution_preset]
    if w <= 0 or h <= 0:
        return None, "⚠️ Width and height must be positive whole numbers."

    ppi = int(custom_ppi or 0) if ppi_preset == "Custom" else PRESET_PPI[ppi_preset]
    if ppi <= 0:
        ppi = 300
    quality = max(10, min(100, int(quality or 90)))
    max_kb = max(0, int(max_kb or 0))
    fmt, ext = OUTPUT_FORMATS.get(output_format, OUTPUT_FORMATS["JPG"])

    valid = [file_path(f) for f in files]
    skipped = [p.name for p in valid if p.suffix.lower() not in IMAGE_EXTENSIONS]
    valid = [p for p in valid if p.suffix.lower() in IMAGE_EXTENSIONS]
    if not valid:
        return None, "⚠️ No supported image files found."

    job = new_job_dir("resize_")
    out_dir = job / "images"
    out_dir.mkdir()
    used = set()
    jobs = [(str(p), str(out_dir / unique_name(p.stem + ext, used))) for p in valid]

    total = len(jobs)
    use_gpu = device != CPU_DEVICE
    workers = 1 if use_gpu else max(1, min(MAX_WORKERS, total))
    pool_cls = ThreadPoolExecutor if (use_gpu or total == 1) else ProcessPoolExecutor
    log.info("Resizing %d images → %dx%d %s @ %d PPI (q%d, max %d KB)", total, w, h, fmt, ppi, quality, max_kb)

    t0 = time.time()
    results = []
    with pool_cls(max_workers=workers) as ex:
        futures = [
            ex.submit(_resize_single_image, src, dst, w, h, maintain_aspect, ppi, quality,
                      USE_PYVIPS, device, fmt, max_kb)
            for src, dst in jobs
        ]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if progress is not None:
                progress(i / total, desc=f"Processed {i}/{total}")

    elapsed = time.time() - t0
    ok = [r for r in results if r["ok"]]
    errors = [r for r in results if not r["ok"]]
    notes = [r for r in ok if r["note"]]
    backend = "PyTorch" if use_gpu else ("pyvips" if USE_PYVIPS and fmt == "JPEG" and not max_kb else "Pillow")
    speed = len(ok) / elapsed if elapsed > 0 else 0

    lines = [
        f"✅ **{len(ok)}/{total}** images processed in **{elapsed:.1f}s** ({speed:.1f} img/s)",
        f"📐 {w} × {h} · 🔘 {ppi} PPI · 🖼️ {output_format}"
        + (f" · 🎨 quality ≤ {quality}" if fmt != "PNG" else "")
        + (f" · 📦 max {max_kb} KB" if max_kb else ""),
        f"⚙️ Workers: {workers} · Device: {device} · Backend: {backend}",
    ]
    if notes:
        lines.append(f"ℹ️ {len(notes)} note(s):")
        lines += [f"  • `{Path(r['src']).name}`: {r['note']}" for r in notes[:10]]
    if errors:
        lines.append(f"⚠️ {len(errors)} error(s):")
        lines += [f"  • `{Path(r['src']).name}`: {r['error']}" for r in errors[:10]]
        if len(errors) > 10:
            lines.append(f"  … and {len(errors) - 10} more")
    if skipped:
        lines.append(f"⏭️ Skipped {len(skipped)} unsupported file(s): " + ", ".join(skipped[:5]))
    status = "\n\n".join(lines)

    outputs = sorted(Path(r["dst"]) for r in ok)
    if not outputs:
        return None, status + "\n\n⚠️ No output files generated."
    if len(outputs) == 1:
        return str(outputs[0]), status
    zip_path = make_zip(outputs, job / f"resized_{stamp()}.zip")
    return zip_path, status
