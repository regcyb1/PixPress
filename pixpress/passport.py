"""Passport photo sheets: print-ready PDF with N copies of each photo."""

import time

from PIL import Image, ImageDraw, ImageOps

from .common import IMAGE_EXTENSIONS, file_path, new_job_dir, stamp
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
    if not files:
        return None, [], "⚠️ Please add at least one photo."

    paths = []
    for f in files:
        fp = file_path(f)
        if fp.suffix.lower() in IMAGE_EXTENSIONS:
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
            img = open_rgb(p)
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
