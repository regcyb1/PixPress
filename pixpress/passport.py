"""Passport photo sheets: print-ready PDF with N copies of each photo."""

import time

from PIL import Image, ImageChops, ImageDraw, ImageOps

from .common import IMAGE_EXTENSIONS, PDF_EXTENSIONS, file_path, new_job_dir, stamp
from .imaging import open_rgb

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
PDF_RENDER_DPI = 300  # resolution used to turn PDF pages into photos
MAX_PDF_PAGES = 50  # safety limit per uploaded PDF



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


# ---------------------------------------------------------------------------
# Inputs: images and PDFs
# ---------------------------------------------------------------------------
def trim_whitespace(img: Image.Image, tolerance: int = 18, pad_ratio: float = 0.01) -> Image.Image:
    """
    Remove near-white borders (e.g. a photo placed in the middle of a PDF page).

    Leaves the image untouched when the content would be tiny or nothing is found.
    """
    rgb = img.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255))).convert("L")
    mask = diff.point(lambda v: 255 if v > tolerance else 0)
    bbox = mask.getbbox()
    if not bbox:
        return img
    l, t, r, b = bbox
    w, h = img.size
    if (r - l) * (b - t) < 0.02 * w * h:  # only specks found – keep the page as is
        return img
    pad = int(round(max(w, h) * pad_ratio))
    return img.crop((max(0, l - pad), max(0, t - pad), min(w, r + pad), min(h, b + pad)))


def _render_pdf(path, job, auto_trim=True):
    """Render every page of a PDF to a PNG photo. Returns list of paths."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(path))
    outs = []
    try:
        n = min(len(doc), MAX_PDF_PAGES)
        for i in range(n):
            page = doc[i]
            img = page.render(scale=PDF_RENDER_DPI / 72).to_pil().convert("RGB")
            page.close()
            if auto_trim:
                img = trim_whitespace(img)
            suffix = f"_page{i + 1}" if n > 1 else ""
            folder = job / f"{len(list(job.iterdir())):03d}"  # keeps names clean and unique
            folder.mkdir()
            out = folder / f"{path.stem}{suffix}.png"
            img.save(out, "PNG")
            outs.append(out)
    finally:
        doc.close()
    return outs


def expand_inputs(files, auto_trim=True):
    """
    Turn uploaded files into a list of image paths.

    Images are used as they are; every page of a PDF becomes one photo
    (with white page borders trimmed when `auto_trim` is on).
    Returns (image_paths, errors).
    """
    paths, errors = [], []
    job = None
    for f in files or []:
        fp = file_path(f)
        ext = fp.suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            paths.append(fp)
        elif ext in PDF_EXTENSIONS:
            job = job or new_job_dir("ppdf_")
            try:
                pages = _render_pdf(fp, job, auto_trim)
                if not pages:
                    errors.append(f"`{fp.name}`: PDF has no pages")
                paths.extend(pages)
            except Exception as exc:
                errors.append(f"`{fp.name}`: can't open PDF – is it password protected? ({type(exc).__name__})")
        else:
            errors.append(f"`{fp.name}`: not an image or PDF")
    return paths, errors


# ---------------------------------------------------------------------------
# Cropping
# ---------------------------------------------------------------------------
def normalize_crop(crop) -> dict:
    """
    Crop settings for one photo: {"rotate": 0/90/180/270, "box": (l, t, w, h) or None}.

    `box` is in fractions (0…1) of the rotated image; None means "largest centred box".
    """
    crop = crop or {}
    box = crop.get("box")
    if box:
        l, t, w, h = (float(v) for v in box)
        l, t = min(max(l, 0.0), 1.0), min(max(t, 0.0), 1.0)
        w, h = min(max(w, 0.0), 1.0 - l), min(max(h, 0.0), 1.0 - t)
        box = (l, t, w, h) if w > 0.001 and h > 0.001 else None
    return {"rotate": int(crop.get("rotate") or 0) % 360, "box": box}


def is_cropped(crop) -> bool:
    c = normalize_crop(crop)
    return bool(c["box"]) or c["rotate"] != 0


def crop_box(size, aspect: float, crop=None):
    """
    Pixel box (left, top, right, bottom) to cut from an image of `size` (after rotation).

    The result always has the photo's aspect ratio (width / height). A saved box with a
    different shape (e.g. the photo size was changed afterwards) is shrunk around its centre.
    """
    w, h = size
    c = normalize_crop(crop)
    if c["box"]:
        l, t, bw, bh = c["box"]
        l, t, bw, bh = l * w, t * h, bw * w, bh * h
    else:
        l, t, bw, bh = 0.0, 0.0, float(w), float(h)
    cx, cy = l + bw / 2, t + bh / 2
    if bw / bh > aspect:
        bw = bh * aspect
    else:
        bh = bw / aspect
    left, top = cx - bw / 2, cy - bh / 2
    return (int(round(left)), int(round(top)), int(round(left + bw)), int(round(top + bh)))


def _rotate(img: Image.Image, degrees: int) -> Image.Image:
    return {90: img.transpose(Image.ROTATE_270), 180: img.transpose(Image.ROTATE_180),
            270: img.transpose(Image.ROTATE_90)}.get(int(degrees) % 360, img)


def apply_crop(img: Image.Image, aspect: float, crop=None) -> Image.Image:
    """Rotate and crop `img` to `aspect` using the crop settings."""
    c = normalize_crop(crop)
    img = _rotate(img, c["rotate"])
    return img.crop(crop_box(img.size, aspect, c))


def _aspect(photo_preset, custom_w, custom_h):
    pw, ph = _resolve_photo_size(photo_preset, custom_w, custom_h)
    return (pw, ph) if pw > 0 and ph > 0 else (None, None)


def cropper_value(path, photo_preset, custom_w, custom_h, crop=None, max_px=900):
    """
    Data for the drag-to-crop widget: a small preview image (data URI), the photo aspect
    ratio and the crop box in fractions of the image.
    """
    import base64
    import io

    pw, ph = _aspect(photo_preset, custom_w, custom_h)
    if not path or not pw:
        return {"src": "", "aspect": 1, "iw": 1, "ih": 1, "box": "0,0,1,1"}
    c = normalize_crop(crop)
    img = _rotate(open_rgb(path), c["rotate"])
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    l, t, r, b = crop_box(img.size, pw / ph, c)
    W, H = img.size
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {
        "src": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(),
        "aspect": pw / ph, "iw": W, "ih": H,
        "box": f"{l / W:.5f},{t / H:.5f},{(r - l) / W:.5f},{(b - t) / H:.5f}",
    }


def describe_crop(path, photo_preset, custom_w, custom_h, crop=None, saved=True):
    """One line telling how the printed area looks: size in mm, pixels and print quality."""
    pw, ph = _aspect(photo_preset, custom_w, custom_h)
    if not path or not pw:
        return ""
    c = normalize_crop(crop)
    img = _rotate(open_rgb(path), c["rotate"])
    l, t, r, b = crop_box(img.size, pw / ph, c)
    dpi = (r - l) / (pw / MM_PER_INCH)
    quality = ("✅ sharp" if dpi >= 250 else "👍 fine" if dpi >= 150
               else "⚠️ low resolution – may print blurry")
    head = "💾 **Crop saved**" if saved else "✂️ Not cropped yet – whole photo is used"
    return (f"{head} · prints at **{pw:g} × {ph:g} mm** from {r - l} × {b - t} px "
            f"(≈ {dpi:.0f} DPI, {quality})")


def cropped_thumbnail(path, photo_preset, custom_w, custom_h, crop=None, max_px=300):
    pw, ph = _aspect(photo_preset, custom_w, custom_h)
    img = open_rgb(path)
    if pw and is_cropped(crop):
        img = apply_crop(img, pw / ph, crop)
    img.thumbnail((max_px, max_px), Image.LANCZOS)
    return img


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
    crops=None,
):
    """
    Build a print-ready PDF with `copies` passport photos of every uploaded image.

    `files` may contain images and PDFs (each PDF page becomes one photo).
    `crops` optionally maps an image path (str) to crop settings (see normalize_crop).

    Returns (pdf_path, preview_images, status_markdown).
    """
    if not files:
        return None, [], "⚠️ Please add at least one photo."

    paths, errors = expand_inputs(files)
    if not paths:
        msg = "⚠️ No supported image or PDF files found."
        return None, [], msg + ("\n\n" + "\n\n".join(errors) if errors else "")
    crops = crops or {}

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
    prepared = []
    for i, p in enumerate(paths):
        try:
            img = open_rgb(p)
            crop = crops.get(str(p))
            if is_cropped(crop):
                img = apply_crop(img, photo_w / photo_h, crop)
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
    pdf_path = str(new_job_dir("passport_") / f"passport_photos_{stamp()}.pdf")
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
