#!/usr/bin/env python3
"""
High-Performance Local Image Resizer
=====================================
A single-file Gradio web application for bulk image resizing.

Run:  python resize_app.py
Open: http://localhost:7860

Features:
  - Resize images to preset or custom dimensions
  - Set PPI/DPI metadata
  - Convert any image format → JPG
  - Parallel batch processing (1000+ images)
  - pyvips (fast) with Pillow fallback
  - Auto EXIF orientation correction
  - ZIP download for batch results
  - Passport photo sheets: print-ready PDF with N copies of each photo
"""

import os
import sys
import time
import shutil
import zipfile
import tempfile
import logging
import pathlib
import struct
from io import BytesIO
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("resizer")

# ---------------------------------------------------------------------------
# Dependency checks & backend selection
# ---------------------------------------------------------------------------
USE_PYVIPS = False
try:
    import pyvips
    USE_PYVIPS = True
    log.info("pyvips %s detected – using high-speed backend.", pyvips.__version__)
except ImportError:
    log.info("pyvips not available – falling back to Pillow.")

try:
    from PIL import Image, ExifTags, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = True  # Handle slightly corrupt files
    log.info("Pillow %s loaded.", Image.__version__)
except ImportError:
    if not USE_PYVIPS:
        sys.exit("ERROR: Neither pyvips nor Pillow is installed. "
                 "Install at least one:\n  pip install Pillow\n  pip install pyvips")

# ---------------------------------------------------------------------------
# GPU / device detection — builds a list of available compute devices
# ---------------------------------------------------------------------------
HAS_TORCH = False
AVAILABLE_DEVICES = ["CPU (Pillow/pyvips)"]
try:
    import torch
    import torch.nn.functional as F  # noqa: N812 – used for GPU resize
    HAS_TORCH = True
    AVAILABLE_DEVICES.append("CPU (PyTorch)")
    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            AVAILABLE_DEVICES.append(f"CUDA:{i} – {torch.cuda.get_device_name(i)}")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        AVAILABLE_DEVICES.append("Apple MPS (Metal)")
    log.info("PyTorch %s loaded. Devices: %s", torch.__version__, AVAILABLE_DEVICES)
except ImportError:
    log.info("PyTorch not installed – GPU acceleration unavailable.")

GPU_INFO = ", ".join(AVAILABLE_DEVICES)
log.info("Available devices: %s", GPU_INFO)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".tiff", ".tif", ".bmp", ".gif"}
MAX_WORKERS = min(os.cpu_count() or 4, 16)  # Cap at 16 to avoid thrashing

PRESET_RESOLUTIONS = {
    "512 × 512": (512, 512),
    "1024 × 1024": (1024, 1024),
    "2048 × 2048": (2048, 2048),
    "4096 × 4096": (4096, 4096),
    "Custom": None,
}

PRESET_PPI = {
    "72": 72,
    "150": 150,
    "300": 300,
    "Custom": None,
}

# --- Passport photo sheet presets (all sizes in millimetres) ---------------
MM_PER_INCH = 25.4

PHOTO_SIZES = {
    "Passport – Nepal / India / UK / EU (35 × 45 mm)": (35.0, 45.0),
    "US Passport / Visa (2 × 2 in)": (50.8, 50.8),
    "China Visa (33 × 48 mm)": (33.0, 48.0),
    "Canada Passport (50 × 70 mm)": (50.0, 70.0),
    "Stamp size (20 × 25 mm)": (20.0, 25.0),
    "Custom": None,
}

PAGE_SIZES = {
    "A4 (210 × 297 mm)": (210.0, 297.0),
    "Letter (8.5 × 11 in)": (215.9, 279.4),
    "A5 (148 × 210 mm)": (148.0, 210.0),
    "4 × 6 in photo paper": (101.6, 152.4),
    "5 × 7 in photo paper": (127.0, 177.8),
    "Legal (8.5 × 14 in)": (215.9, 355.6),
}

SHEET_DPI = 300  # print resolution for generated PDF pages

# ---------------------------------------------------------------------------
# EXIF orientation helpers (Pillow path)
# ---------------------------------------------------------------------------
def _apply_exif_orientation_pillow(img: "Image.Image") -> "Image.Image":
    """Transpose a Pillow image according to its EXIF Orientation tag."""
    try:
        exif = img.getexif()
        orientation = exif.get(0x0112)  # Orientation tag
        if orientation is None:
            return img
        transforms = {
            2: Image.FLIP_LEFT_RIGHT,
            3: Image.ROTATE_180,
            4: Image.FLIP_TOP_BOTTOM,
            5: Image.TRANSPOSE,
            6: Image.ROTATE_270,
            7: Image.TRANSVERSE,
            8: Image.ROTATE_90,
        }
        if orientation in transforms:
            img = img.transpose(transforms[orientation])
    except Exception:
        pass
    return img


def _to_rgb_pillow(img: "Image.Image") -> "Image.Image":
    """Convert any Pillow image to RGB, flattening transparency onto white."""
    if img.mode in ("RGBA", "LA", "PA", "P") and (
        img.mode != "P" or "transparency" in img.info
    ):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[3])
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _open_rgb(path) -> "Image.Image":
    """Open an image file, fix EXIF orientation and return it as RGB."""
    img = Image.open(str(path))
    img = _apply_exif_orientation_pillow(img)
    return _to_rgb_pillow(img)


# ---------------------------------------------------------------------------
# Core resize function (runs in worker process)
# ---------------------------------------------------------------------------
def _resize_single_image(
    input_path: str,
    output_dir: str,
    width: int,
    height: int,
    maintain_aspect: bool,
    ppi: int,
    quality: int,
    use_pyvips: bool,
    device: str = "CPU (Pillow/pyvips)",
) -> dict:
    """
    Resize a single image file and save as JPG.

    Returns a dict with keys: ok (bool), src (str), dst (str), error (str|None).
    """
    src = Path(input_path)
    stem = src.stem
    dst = Path(output_dir) / f"{stem}.jpg"

    try:
        # Route to the appropriate backend
        if device != "CPU (Pillow/pyvips)":
            return _resize_torch_gpu(src, dst, width, height, maintain_aspect, ppi, quality, device)
        elif use_pyvips:
            return _resize_pyvips(src, dst, width, height, maintain_aspect, ppi, quality)
        else:
            return _resize_pillow(src, dst, width, height, maintain_aspect, ppi, quality)
    except Exception as exc:
        return {"ok": False, "src": str(src), "dst": str(dst), "error": str(exc)}


def _resize_pyvips(src, dst, w, h, maintain_aspect, ppi, quality):
    """Resize using pyvips (extremely fast, low memory)."""
    img = pyvips.Image.new_from_file(str(src), access="sequential")

    # Auto-rotate based on EXIF
    img = img.autorot()

    # Calculate scale factors
    if maintain_aspect:
        scale = min(w / img.width, h / img.height)
        img = img.resize(scale)
    else:
        h_scale = w / img.width
        v_scale = h / img.height
        img = img.resize(h_scale, vscale=v_scale)

    # Flatten alpha channel to white background
    if img.hasalpha():
        img = img.flatten(background=[255, 255, 255])

    # Convert to sRGB if needed
    if img.interpretation != "srgb":
        img = img.colourspace("srgb")

    # Set PPI in JFIF metadata
    img.jpegsave(
        str(dst),
        Q=quality,
        optimize_coding=True,
        interlace=True,  # progressive
        strip=True,
    )

    # Patch DPI into the saved JPEG via JFIF header (pyvips strip removes it)
    _patch_jpeg_dpi(str(dst), ppi)

    return {"ok": True, "src": str(src), "dst": str(dst), "error": None}


def _patch_jpeg_dpi(filepath: str, ppi: int):
    """Patch the JFIF APP0 header to set DPI on an existing JPEG file."""
    try:
        with open(filepath, "r+b") as f:
            data = f.read(20)
            # Look for JFIF marker: FF D8 FF E0 xx xx 'JFIF\x00'
            if data[0:2] == b'\xff\xd8' and data[2:4] == b'\xff\xe0':
                jfif_start = 4
                length = struct.unpack(">H", data[4:6])[0]
                if data[6:11] == b'JFIF\x00':
                    # Units byte at offset 11 (1 = DPI)
                    f.seek(11)
                    f.write(b'\x01')
                    # X density at offset 12-13, Y density at offset 14-15 (big-endian)
                    f.seek(12)
                    f.write(struct.pack(">HH", ppi, ppi))
    except Exception:
        pass  # Non-critical: DPI metadata is best-effort


def _resize_pillow(src, dst, w, h, maintain_aspect, ppi, quality):
    """Resize using Pillow (universal fallback)."""
    # Open, fix EXIF orientation, flatten alpha / convert to RGB
    img = _open_rgb(src)

    # Resize
    if maintain_aspect:
        img.thumbnail((w, h), Image.LANCZOS)
    else:
        img = img.resize((w, h), Image.LANCZOS)

    # Save JPEG
    img.save(
        str(dst),
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        dpi=(ppi, ppi),
    )

    return {"ok": True, "src": str(src), "dst": str(dst), "error": None}


def _resize_torch_gpu(src, dst, w, h, maintain_aspect, ppi, quality, device_label):
    """Resize using PyTorch on GPU (CUDA or Apple MPS) or CPU."""
    import torch
    import torch.nn.functional as F

    # Determine torch device string from the UI label
    if "CUDA" in device_label:
        # e.g. "CUDA:0 – GeForce RTX 3090" → "cuda:0"
        dev = "cuda:" + device_label.split(":")[1].split(" ")[0]
    elif "MPS" in device_label:
        dev = "mps"
    else:
        dev = "cpu"

    # Load with Pillow (handles format diversity + EXIF), convert to RGB
    img = _open_rgb(src)

    # Calculate target size
    if maintain_aspect:
        scale = min(w / img.width, h / img.height)
        new_w, new_h = int(img.width * scale), int(img.height * scale)
    else:
        new_w, new_h = w, h

    # Convert to tensor → GPU → resize → back to CPU
    import numpy as np
    arr = np.array(img, dtype=np.float32) / 255.0  # (H, W, 3)
    tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)  # (1, 3, H, W)
    tensor = tensor.to(dev)

    resized = F.interpolate(tensor, size=(new_h, new_w), mode="bilinear", align_corners=False)

    # Move back to CPU and convert to PIL
    result = resized.squeeze(0).permute(1, 2, 0).cpu().clamp(0, 1).numpy()
    result_img = Image.fromarray((result * 255).astype(np.uint8), "RGB")

    # Save as JPEG
    result_img.save(
        str(dst),
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
        dpi=(ppi, ppi),
    )

    return {"ok": True, "src": str(src), "dst": str(dst), "error": None}


# ---------------------------------------------------------------------------
# Batch processing orchestrator
# ---------------------------------------------------------------------------
def process_images(
    files,
    resolution_preset: str,
    custom_width: int,
    custom_height: int,
    maintain_aspect: bool,
    ppi_preset: str,
    custom_ppi: int,
    quality: int,
    device: str = "CPU (Pillow/pyvips)",
    progress=None,
):
    """
    Process a list of uploaded files.

    Returns (output_path, status_message).
    output_path is either a single .jpg or a .zip file path.
    """
    if not files:
        return None, "⚠️ No files uploaded."

    # --- Resolve parameters ---
    if resolution_preset == "Custom":
        w, h = int(custom_width), int(custom_height)
    else:
        w, h = PRESET_RESOLUTIONS[resolution_preset]

    if w <= 0 or h <= 0:
        return None, "⚠️ Width and height must be positive integers."

    if ppi_preset == "Custom":
        ppi = int(custom_ppi)
    else:
        ppi = PRESET_PPI[ppi_preset]

    if ppi <= 0:
        ppi = 300

    quality = max(70, min(100, int(quality)))

    # --- Filter valid image files ---
    valid_files = []
    for f in files:
        fp = Path(f) if isinstance(f, str) else Path(f.name)
        if fp.suffix.lower() in SUPPORTED_EXTENSIONS:
            valid_files.append(str(fp))
        else:
            log.warning("Skipping unsupported file: %s", fp.name)

    if not valid_files:
        return None, "⚠️ No supported image files found."

    total = len(valid_files)
    log.info("Processing %d images → %dx%d @ %d PPI, quality %d", total, w, h, ppi, quality)

    # --- Create temp output directory ---
    output_dir = tempfile.mkdtemp(prefix="resizer_out_")

    # --- Process images in parallel ---
    t0 = time.time()
    results = []
    errors = []
    completed = 0

    # Use slightly fewer workers than CPUs to keep system responsive
    workers = max(1, min(MAX_WORKERS, total))

    # GPU processing uses ThreadPoolExecutor (GPU ops release GIL) or serial
    # CPU processing uses ProcessPoolExecutor for true parallelism
    use_gpu = device != "CPU (Pillow/pyvips)"

    if use_gpu:
        # GPU: process sequentially to avoid GPU memory contention
        from concurrent.futures import ThreadPoolExecutor
        PoolClass = ThreadPoolExecutor
        workers = 1  # GPU serialised
    else:
        PoolClass = ProcessPoolExecutor

    with PoolClass(max_workers=workers) as executor:
        futures = {
            executor.submit(
                _resize_single_image,
                fp, output_dir, w, h, maintain_aspect, ppi, quality, USE_PYVIPS, device,
            ): fp
            for fp in valid_files
        }

        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            if not result["ok"]:
                errors.append(result)
            completed += 1
            if progress is not None:
                progress(completed / total, desc=f"Processed {completed}/{total}")

    elapsed = time.time() - t0
    ok_count = sum(1 for r in results if r["ok"])
    err_count = len(errors)

    # --- Status summary ---
    speed = ok_count / elapsed if elapsed > 0 else 0
    status_lines = [
        f"✅ **{ok_count}/{total}** images processed in **{elapsed:.1f}s** ({speed:.1f} img/s)",
        f"📐 Resolution: {w} × {h} | 🔘 PPI: {ppi} | 🎨 Quality: {quality}",
        f"⚙️ Workers: {workers} | Device: {device} | Backend: {'pyvips' if USE_PYVIPS and not use_gpu else 'PyTorch GPU' if use_gpu else 'Pillow'}",
    ]
    if err_count:
        status_lines.append(f"⚠️ {err_count} error(s):")
        for e in errors[:10]:
            status_lines.append(f"  • `{Path(e['src']).name}`: {e['error']}")
        if err_count > 10:
            status_lines.append(f"  … and {err_count - 10} more")

    status_msg = "\n".join(status_lines)

    # --- Package output ---
    output_files = sorted(Path(output_dir).glob("*.jpg"))

    if len(output_files) == 0:
        return None, status_msg + "\n\n⚠️ No output files generated."

    if len(output_files) == 1:
        # Single file: return it directly
        return str(output_files[0]), status_msg

    # Multiple files: create ZIP
    zip_path = os.path.join(tempfile.gettempdir(), "resized_images.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in output_files:
            zf.write(fp, fp.name)

    # Clean up temp dir (ZIP has the files now)
    shutil.rmtree(output_dir, ignore_errors=True)

    return zip_path, status_msg


# ---------------------------------------------------------------------------
# Passport photo sheet (print-ready PDF)
# ---------------------------------------------------------------------------
def _mm_to_px(mm: float, dpi: int = SHEET_DPI) -> int:
    return int(round(mm / MM_PER_INCH * dpi))


def _resolve_photo_size(preset: str, custom_w, custom_h):
    """Return (width_mm, height_mm) for the selected photo size preset."""
    if preset == "Custom" or PHOTO_SIZES.get(preset) is None:
        return float(custom_w or 0), float(custom_h or 0)
    return PHOTO_SIZES[preset]


def _resolve_page_size(preset: str, orientation: str):
    """Return (width_mm, height_mm) of the page, honouring orientation."""
    w, h = PAGE_SIZES[preset]
    if orientation == "Landscape":
        w, h = max(w, h), min(w, h)
    else:
        w, h = min(w, h), max(w, h)
    return w, h


def _sheet_grid(page_w, page_h, photo_w, photo_h, margin, gap):
    """
    Work out how many photos fit on a page.

    Returns (cols, rows, x0, y0) where x0/y0 are the top-left offsets (mm)
    of the grid. The grid is centred horizontally and starts at the top
    margin, so any leftover paper stays in one piece at the bottom.
    """
    usable_w = page_w - 2 * margin
    usable_h = page_h - 2 * margin
    if photo_w <= 0 or photo_h <= 0 or usable_w <= 0 or usable_h <= 0:
        return 0, 0, 0.0, 0.0
    cols = int((usable_w + gap) // (photo_w + gap))
    rows = int((usable_h + gap) // (photo_h + gap))
    grid_w = cols * photo_w + max(cols - 1, 0) * gap
    x0 = margin + (usable_w - grid_w) / 2
    y0 = margin
    return cols, rows, x0, y0


def _assign_slots(n_photos: int, copies: int, per_page: int, keep_together: bool):
    """
    Assign each copy of each photo to a global slot index (page * per_page + cell).

    Copies are placed one after another in reading order. With keep_together,
    a photo's copies are never split across two pages (when they fit on one).
    """
    placements = []  # list of (photo_index, slot)
    slot = 0
    for idx in range(n_photos):
        if keep_together and copies <= per_page:
            left_on_page = per_page - (slot % per_page)
            if left_on_page < copies:
                slot += left_on_page
        for _ in range(copies):
            placements.append((idx, slot))
            slot += 1
    return placements


def describe_sheet_layout(photo_preset, custom_w, custom_h, page_preset, orientation,
                          margin, gap, copies, files=None):
    """Short markdown summary of how the sheet will be laid out."""
    pw, ph = _resolve_photo_size(photo_preset, custom_w, custom_h)
    page_w, page_h = _resolve_page_size(page_preset, orientation)
    cols, rows, _, _ = _sheet_grid(page_w, page_h, pw, ph, float(margin or 0), float(gap or 0))
    per_page = cols * rows
    if per_page == 0:
        return ("⚠️ **Photo does not fit on this page.** "
                "Try a bigger page, smaller margins or landscape orientation.")

    copies = max(1, int(copies or 1))
    lines = [
        f"📄 **{per_page} photos per page** ({cols} across × {rows} down) "
        f"&nbsp;·&nbsp; photo {pw:g} × {ph:g} mm on {page_w:g} × {page_h:g} mm",
    ]
    n = len(files) if files else 0
    if n:
        placements = _assign_slots(n, copies, per_page, True)
        pages = placements[-1][1] // per_page + 1
        lines.append(
            f"🧾 {n} photo(s) × {copies} copies = **{n * copies} prints** "
            f"on **{pages} page(s)**"
        )
    return "\n\n".join(lines)


def make_passport_sheet(
    files,
    photo_preset: str,
    custom_w: float,
    custom_h: float,
    page_preset: str,
    orientation: str,
    copies: int,
    margin: float,
    gap: float,
    fit_mode: str,
    keep_together: bool,
    cut_guides: bool,
    progress=None,
):
    """
    Build a print-ready PDF with `copies` passport photos of every uploaded image.

    Returns (pdf_path, preview_images, status_markdown).
    """
    from PIL import ImageDraw, ImageOps

    if not files:
        return None, [], "⚠️ Please add at least one photo."

    paths = []
    for f in files:
        fp = Path(f) if isinstance(f, str) else Path(f.name)
        if fp.suffix.lower() in SUPPORTED_EXTENSIONS:
            paths.append(fp)
    if not paths:
        return None, [], "⚠️ No supported image files found."

    photo_w, photo_h = _resolve_photo_size(photo_preset, custom_w, custom_h)
    if photo_w <= 0 or photo_h <= 0:
        return None, [], "⚠️ Photo width and height must be greater than 0."

    page_w, page_h = _resolve_page_size(page_preset, orientation)
    margin = max(0.0, float(margin or 0))
    gap = max(0.0, float(gap or 0))
    copies = max(1, int(copies or 1))

    cols, rows, x0, y0 = _sheet_grid(page_w, page_h, photo_w, photo_h, margin, gap)
    per_page = cols * rows
    if per_page == 0:
        return None, [], ("⚠️ The photo does not fit on the selected page. "
                          "Use a bigger page, smaller margins or landscape orientation.")

    t0 = time.time()
    photo_px = (_mm_to_px(photo_w), _mm_to_px(photo_h))

    # --- Prepare each photo once at exact print size ---
    prepared, errors = [], []
    for i, p in enumerate(paths):
        try:
            img = _open_rgb(p)
            if fit_mode.startswith("Fit"):
                img = ImageOps.pad(img, photo_px, Image.LANCZOS, color=(255, 255, 255))
            else:
                img = ImageOps.fit(img, photo_px, Image.LANCZOS, centering=(0.5, 0.5))
            prepared.append(img)
        except Exception as exc:  # unreadable / corrupt file
            errors.append(f"`{p.name}`: not a readable image ({type(exc).__name__})")
        if progress is not None:
            progress((i + 1) / (len(paths) + 1), desc=f"Preparing photo {i + 1}/{len(paths)}")

    if not prepared:
        return None, [], "⚠️ None of the photos could be read.\n\n" + "\n".join(errors)

    # --- Lay out pages ---
    placements = _assign_slots(len(prepared), copies, per_page, keep_together)
    n_pages = placements[-1][1] // per_page + 1
    page_px = (_mm_to_px(page_w), _mm_to_px(page_h))
    pages = [Image.new("RGB", page_px, (255, 255, 255)) for _ in range(n_pages)]
    draws = [ImageDraw.Draw(pg) for pg in pages] if cut_guides else []

    for idx, slot in placements:
        page_no, cell = divmod(slot, per_page)
        r, c = divmod(cell, cols)
        x = _mm_to_px(x0 + c * (photo_w + gap))
        y = _mm_to_px(y0 + r * (photo_h + gap))
        pages[page_no].paste(prepared[idx], (x, y))
        if cut_guides:
            draws[page_no].rectangle(
                [x - 1, y - 1, x + photo_px[0], y + photo_px[1]],
                outline=(160, 160, 160), width=1,
            )

    if progress is not None:
        progress(0.95, desc="Writing PDF…")

    # --- Save PDF ---
    out_dir = tempfile.mkdtemp(prefix="passport_sheet_")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    pdf_path = os.path.join(out_dir, f"passport_photos_{stamp}.pdf")
    pages[0].save(
        pdf_path, "PDF",
        save_all=True, append_images=pages[1:],
        resolution=SHEET_DPI, quality=95,
    )

    # --- Small previews for the UI ---
    previews = []
    for i, pg in enumerate(pages):
        thumb = pg.copy()
        thumb.thumbnail((900, 900), Image.LANCZOS)
        previews.append((thumb, f"Page {i + 1} of {n_pages}"))

    elapsed = time.time() - t0
    status = [
        f"✅ **PDF ready** — {len(prepared)} photo(s) × {copies} copies = "
        f"**{len(placements)} prints** on **{n_pages} page(s)** ({elapsed:.1f}s)",
        f"📄 {page_preset}, {orientation.lower()} &nbsp;·&nbsp; 📐 {photo_w:g} × {photo_h:g} mm "
        f"&nbsp;·&nbsp; {per_page} per page &nbsp;·&nbsp; {SHEET_DPI} DPI",
        "🖨️ **Print at 100 % / “Actual size”** — turn off “Fit to page” so photos keep their exact size.",
    ]
    if errors:
        status.append(f"⚠️ Skipped {len(errors)} file(s):")
        status.extend(f"  • {e}" for e in errors[:10])
    return pdf_path, previews, "\n\n".join(status)


# ---------------------------------------------------------------------------
# Gradio UI
# ---------------------------------------------------------------------------
CUSTOM_CSS = """
.gradio-container { max-width: 1180px !important; margin: auto; }

#app-header {
    text-align: center;
    padding: 28px 16px 18px;
    margin-bottom: 8px;
    border-radius: 18px;
    background: linear-gradient(135deg, rgba(102,126,234,.14), rgba(118,75,162,.14));
    border: 1px solid rgba(128,128,128,.18);
}
#app-header h1 {
    margin: 0;
    font-size: 2.3rem;
    font-weight: 800;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}
#app-header p { margin: 6px 0 12px; opacity: .72; font-size: 1rem; }
.badges { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; }
.badge {
    font-size: .78rem; padding: 4px 10px; border-radius: 999px;
    background: rgba(102,126,234,.14); border: 1px solid rgba(102,126,234,.3);
}

.card {
    border: 1px solid rgba(128,128,128,.2) !important;
    border-radius: 14px !important;
    padding: 6px !important;
}
.step-title h3 { margin: 4px 4px 0 !important; font-size: 1.02rem !important; }
.hint { opacity: .7; font-size: .88rem; }

.primary-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: #fff !important;
    font-weight: 700 !important;
    font-size: 1.05rem !important;
    border: none !important;
    border-radius: 12px !important;
    min-height: 52px;
    transition: transform .15s ease, box-shadow .15s ease;
}
.primary-btn:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 18px rgba(102,126,234,.35);
}
.status-box {
    min-height: 72px;
    padding: 10px 14px !important;
    border-radius: 12px;
    background: rgba(128,128,128,.06);
}
#layout-info { padding: 10px 14px; border-radius: 12px; background: rgba(102,126,234,.08); }
footer { display: none !important; }
"""


def build_ui():
    """Construct and return the Gradio Blocks interface."""
    try:
        import gradio as gr
    except ImportError:
        sys.exit("ERROR: Gradio is not installed.\n  pip install gradio")

    theme = gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="purple",
        neutral_hue="slate",
        radius_size="lg",
    )

    backend = "pyvips" if USE_PYVIPS else "Pillow"
    device_badges = "".join(f"<span class='badge'>🖥️ {d}</span>" for d in AVAILABLE_DEVICES)

    with gr.Blocks(title="Image Resizer") as app:
        # ------------------------------------------------------------------
        # Header
        # ------------------------------------------------------------------
        gr.HTML(
            f"""
            <div id="app-header">
              <h1>⚡ Image Resizer</h1>
              <p>Resize photos in bulk or print passport photos at home — everything stays on your computer.</p>
              <div class="badges">
                <span class="badge">⚙️ Backend: {backend}</span>
                <span class="badge">🧵 {MAX_WORKERS} workers</span>
                {device_badges}
              </div>
            </div>
            """
        )

        with gr.Tabs():
            # ==============================================================
            # TAB 1 — Bulk resize
            # ==============================================================
            with gr.Tab("🖼️ Bulk Resize"):
                with gr.Row(equal_height=False):
                    # ---- Left: inputs & settings ----
                    with gr.Column(scale=6):
                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 1 · Add images", elem_classes="step-title")
                            file_input = gr.File(
                                label="Drop images here or click to browse",
                                file_types=["image"],
                                file_count="multiple",
                                height=180,
                            )

                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 2 · Choose size", elem_classes="step-title")
                            resolution_preset = gr.Dropdown(
                                choices=list(PRESET_RESOLUTIONS.keys()),
                                value="1024 × 1024",
                                label="Output size",
                            )
                            with gr.Row(visible=False) as custom_size_row:
                                custom_width = gr.Number(
                                    value=1024, label="Width (px)",
                                    precision=0, minimum=1, maximum=16384,
                                )
                                custom_height = gr.Number(
                                    value=1024, label="Height (px)",
                                    precision=0, minimum=1, maximum=16384,
                                )
                            maintain_aspect = gr.Checkbox(
                                value=True,
                                label="Keep proportions (fit inside the size, no stretching)",
                            )

                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 3 · Print resolution", elem_classes="step-title")
                            with gr.Row():
                                ppi_preset = gr.Radio(
                                    choices=list(PRESET_PPI.keys()),
                                    value="300",
                                    label="PPI / DPI",
                                    info="72 = screen · 300 = print",
                                )
                                custom_ppi = gr.Number(
                                    value=300, label="Custom PPI",
                                    precision=0, minimum=1, maximum=2400,
                                    visible=False,
                                )

                        with gr.Accordion("⚙️ Advanced options", open=False):
                            quality = gr.Slider(
                                minimum=70, maximum=100, step=1, value=90,
                                label="JPEG quality",
                                info="Higher = better quality, bigger files",
                            )
                            device_selector = gr.Dropdown(
                                choices=AVAILABLE_DEVICES,
                                value=AVAILABLE_DEVICES[0],
                                label="Compute device",
                                info="Pick a GPU for hardware acceleration (requires PyTorch)",
                            )
                            gr.Markdown(
                                "<span class='hint'>Output is always <b>JPG</b> "
                                "(optimized, progressive). Transparent areas become white.</span>"
                            )

                    # ---- Right: action & result ----
                    with gr.Column(scale=5):
                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 4 · Resize & download", elem_classes="step-title")
                            process_btn = gr.Button(
                                "⚡ Resize Images",
                                variant="primary",
                                elem_classes="primary-btn",
                                size="lg",
                            )
                            status_output = gr.Markdown(
                                value="<span class='hint'>Add images, choose a size, "
                                      "then click <b>Resize Images</b>.</span>",
                                elem_classes="status-box",
                            )
                            file_output = gr.File(label="📥 Download result", interactive=False)
                            clear_btn = gr.Button("🧹 Clear", variant="secondary", size="sm")

            # ==============================================================
            # TAB 2 — Passport photo sheet
            # ==============================================================
            with gr.Tab("🪪 Passport Photo Sheet"):
                gr.Markdown(
                    "<span class='hint'>Add one or more photos — each one is printed "
                    "several times on a sheet you can print at home and cut out.</span>"
                )
                with gr.Row(equal_height=False):
                    # ---- Left: inputs & settings ----
                    with gr.Column(scale=6):
                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 1 · Add photos", elem_classes="step-title")
                            pp_files = gr.File(
                                label="Drop photos here (multiple allowed)",
                                file_types=["image"],
                                file_count="multiple",
                                height=160,
                            )
                            pp_gallery = gr.Gallery(
                                label="Selected photos",
                                columns=6, height=150,
                                object_fit="cover",
                                show_label=False,
                                visible=False,
                            )

                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 2 · Photo size & copies", elem_classes="step-title")
                            pp_size = gr.Dropdown(
                                choices=list(PHOTO_SIZES.keys()),
                                value=next(iter(PHOTO_SIZES)),
                                label="Photo size",
                            )
                            with gr.Row(visible=False) as pp_custom_row:
                                pp_custom_w = gr.Number(value=35, label="Width (mm)", minimum=5, maximum=300)
                                pp_custom_h = gr.Number(value=45, label="Height (mm)", minimum=5, maximum=300)
                            pp_copies = gr.Slider(
                                minimum=1, maximum=30, step=1, value=2,
                                label="Copies of each photo",
                            )

                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 3 · Paper", elem_classes="step-title")
                            with gr.Row():
                                pp_page = gr.Dropdown(
                                    choices=list(PAGE_SIZES.keys()),
                                    value=next(iter(PAGE_SIZES)),
                                    label="Page size",
                                )
                                pp_orient = gr.Radio(
                                    choices=["Portrait", "Landscape"],
                                    value="Portrait",
                                    label="Orientation",
                                )

                        with gr.Accordion("⚙️ Layout options", open=False):
                            with gr.Row():
                                pp_margin = gr.Number(
                                    value=5, label="Page margin (mm)", minimum=0, maximum=50,
                                    info="Most home printers need ≥ 5 mm",
                                )
                                pp_gap = gr.Number(
                                    value=3, label="Space between photos (mm)", minimum=0, maximum=30,
                                )
                            pp_fit = gr.Radio(
                                choices=["Crop to fill (recommended)", "Fit whole photo (white bars)"],
                                value="Crop to fill (recommended)",
                                label="If the photo shape doesn't match",
                            )
                            with gr.Row():
                                pp_keep = gr.Checkbox(
                                    value=True, label="Don't split a photo's copies across pages",
                                )
                                pp_guides = gr.Checkbox(
                                    value=True, label="Draw cutting guides",
                                )

                    # ---- Right: action, preview & result ----
                    with gr.Column(scale=5):
                        with gr.Group(elem_classes="card"):
                            gr.Markdown("### 4 · Create PDF", elem_classes="step-title")
                            pp_layout_info = gr.Markdown(elem_id="layout-info")
                            pp_btn = gr.Button(
                                "🖨️ Create Printable PDF",
                                variant="primary",
                                elem_classes="primary-btn",
                                size="lg",
                            )
                            pp_status = gr.Markdown(
                                value="<span class='hint'>Your PDF and a page preview will appear here.</span>",
                                elem_classes="status-box",
                            )
                            pp_pdf = gr.File(label="📥 Download PDF", interactive=False)
                            pp_preview = gr.Gallery(
                                label="Page preview",
                                columns=1, height=520,
                                object_fit="contain",
                                preview=True,
                            )

        # ------------------------------------------------------------------
        # Bulk resize — interaction logic
        # ------------------------------------------------------------------
        def _on_resolution_change(preset):
            if preset == "Custom":
                return gr.update(visible=True), gr.update(), gr.update()
            w, h = PRESET_RESOLUTIONS[preset]
            return gr.update(visible=False), gr.update(value=w), gr.update(value=h)

        resolution_preset.change(
            fn=_on_resolution_change,
            inputs=[resolution_preset],
            outputs=[custom_size_row, custom_width, custom_height],
        )

        def _on_ppi_change(preset):
            if preset == "Custom":
                return gr.update(visible=True)
            return gr.update(value=PRESET_PPI[preset], visible=False)

        ppi_preset.change(fn=_on_ppi_change, inputs=[ppi_preset], outputs=[custom_ppi])

        def _run_processing(
            files, res_preset, c_width, c_height, aspect, ppi_p, c_ppi, qual, dev, progress=gr.Progress()
        ):
            output_path, status = process_images(
                files, res_preset, c_width, c_height, aspect, ppi_p, c_ppi, qual, dev, progress
            )
            return status, output_path

        process_btn.click(
            fn=_run_processing,
            inputs=[
                file_input, resolution_preset,
                custom_width, custom_height, maintain_aspect,
                ppi_preset, custom_ppi, quality, device_selector,
            ],
            outputs=[status_output, file_output],
        )

        clear_btn.click(
            fn=lambda: (None, None, "<span class='hint'>Cleared. Add new images to start again.</span>"),
            outputs=[file_input, file_output, status_output],
        )

        # ------------------------------------------------------------------
        # Passport sheet — interaction logic
        # ------------------------------------------------------------------
        layout_inputs = [pp_size, pp_custom_w, pp_custom_h, pp_page, pp_orient,
                         pp_margin, pp_gap, pp_copies, pp_files]

        def _on_pp_size_change(preset):
            return gr.update(visible=(preset == "Custom"))

        pp_size.change(fn=_on_pp_size_change, inputs=[pp_size], outputs=[pp_custom_row])

        def _on_pp_files_change(files):
            if not files:
                return gr.update(value=None, visible=False)
            paths = [f if isinstance(f, str) else f.name for f in files]
            return gr.update(value=paths, visible=True)

        pp_files.change(fn=_on_pp_files_change, inputs=[pp_files], outputs=[pp_gallery])

        for comp in layout_inputs:
            comp.change(fn=describe_sheet_layout, inputs=layout_inputs, outputs=[pp_layout_info])
        app.load(fn=describe_sheet_layout, inputs=layout_inputs, outputs=[pp_layout_info])

        def _run_sheet(files, size, cw, ch, page, orient, copies, margin, gap, fit, keep, guides,
                       progress=gr.Progress()):
            pdf, previews, status = make_passport_sheet(
                files, size, cw, ch, page, orient, copies, margin, gap, fit, keep, guides, progress
            )
            return status, pdf, previews

        pp_btn.click(
            fn=_run_sheet,
            inputs=[pp_files, pp_size, pp_custom_w, pp_custom_h, pp_page, pp_orient,
                    pp_copies, pp_margin, pp_gap, pp_fit, pp_keep, pp_guides],
            outputs=[pp_status, pp_pdf, pp_preview],
        )

    return app, theme, CUSTOM_CSS


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _kill_port(port: int):
    """Kill any process occupying the given port (cross-platform)."""
    import subprocess
    try:
        if sys.platform == "win32":
            out = subprocess.check_output(
                f"netstat -ano | findstr :{port}", shell=True, text=True
            )
            for line in out.strip().splitlines():
                pid = line.strip().split()[-1]
                if pid.isdigit():
                    subprocess.call(f"taskkill /F /PID {pid}", shell=True)
        else:
            subprocess.call(f"lsof -ti :{port} | xargs kill -9 2>/dev/null", shell=True)
        log.info("Cleared port %d.", port)
    except Exception:
        pass  # Nothing to kill


def main():
    log.info("=" * 60)
    log.info("  Image Resizer — Starting up")
    log.info("  Backend : %s", "pyvips" if USE_PYVIPS else "Pillow")
    log.info("  Devices : %s", GPU_INFO)
    log.info("  Workers : %d", MAX_WORKERS)
    log.info("=" * 60)

    # Free port 7860 if a stale process is using it
    _kill_port(7860)

    app, theme, css = build_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
        theme=theme,
        css=css,
    )


if __name__ == "__main__":
    main()
