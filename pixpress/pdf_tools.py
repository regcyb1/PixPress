"""PDF tools: merge PDFs and images, compress, organize/split, PDF → images, passwords."""

import re
import time
from io import BytesIO

from PIL import Image
from pypdf import PageObject, PdfReader, PdfWriter, Transformation

from .common import (IMAGE_EXTENSIONS, PDF_EXTENSIONS, file_path, human_size, log, make_zip,
                     natural_key, new_job_dir, stamp, unique_name)
from .imaging import open_rgb

PT_PER_MM = 72 / 25.4
LOSSLESS_IMAGE_QUALITY = 95

# label → (JPEG quality, max image side in px); None = lossless only; "target" = aim for a size
COMPRESSION_LEVELS = {
    "None – keep original quality": None,
    "Light – high quality": (85, 3000),
    "Balanced – recommended": (70, 2000),
    "Strong – smallest file": (50, 1400),
    "Target size (MB)": "target",
}
# tried in order (lightest first) until the file fits the requested size
TARGET_STEPS = [(85, 3000), (75, 2400), (65, 2000), (55, 1600), (45, 1300), (35, 1000), (25, 800), (20, 600)]

PDF_PAGE_SIZES = {
    "Fit page to each image": None,
    "A4": (210.0, 297.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "A5": (148.0, 210.0),
}

ORDER_OPTIONS = ["As uploaded", "Name A → Z", "Name Z → A"]

ORGANIZE_MODES = [
    "Keep only these pages (in this order)",
    "Remove these pages",
    "Split – each range becomes its own PDF",
    "Split – every page becomes its own PDF",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _open_pdf(path, password: str = "") -> PdfReader:
    reader = PdfReader(str(path))
    if reader.is_encrypted and not reader.decrypt(password or ""):
        raise ValueError("password protected – unlock it first (🔐 Password tab)")
    return reader


def _to_bytes(writer: PdfWriter) -> bytes:
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _supported(paths, exts):
    return [p for p in paths if p.suffix.lower() in exts]


def parse_ranges(text: str, n_pages: int) -> list:
    """Parse '1-3, 5, 8-end' into groups of 0-based page indexes.

    Each comma-separated part is one group. Reversed ranges ('5-3') are allowed.
    """
    groups = []
    for part in re.split(r"[,;]", text or ""):
        part = part.strip().lower().replace(" ", "")
        if not part:
            continue
        if part in ("all", "*"):
            groups.append(list(range(n_pages)))
            continue
        m = re.fullmatch(r"(\d*)-(\d*|end|last)", part)
        if m:
            a = int(m[1]) if m[1] else 1
            b = n_pages if m[2] in ("", "end", "last") else int(m[2])
        elif part.isdigit():
            a = b = int(part)
        elif part in ("end", "last"):
            a = b = n_pages
        else:
            raise ValueError(f"Can't understand “{part}”. Use e.g. 1-3, 5, 8-end")
        for x in (a, b):
            if not 1 <= x <= n_pages:
                raise ValueError(f"Page {x} doesn't exist – the PDF has {n_pages} page(s).")
        step = 1 if b >= a else -1
        groups.append([i - 1 for i in range(a, b + step, step)])
    return groups


def order_paths(files, order: str = ORDER_OPTIONS[0], custom: str = "") -> list:
    """Supported input paths in the order the user asked for."""
    paths = _supported([file_path(f) for f in files or []], IMAGE_EXTENSIONS | PDF_EXTENSIONS)
    if custom and custom.strip():
        try:
            idx = [int(x) - 1 for x in re.split(r"[,\s]+", custom.strip()) if x]
        except ValueError:
            raise ValueError("Custom order must be numbers like 3, 1, 2")
        bad = [i + 1 for i in idx if not 0 <= i < len(paths)]
        if bad:
            raise ValueError(f"No file number {bad[0]} – there are {len(paths)} file(s).")
        seen = []
        for i in idx:
            if i not in seen:
                seen.append(i)
        seen += [i for i in range(len(paths)) if i not in seen]  # unlisted files keep their place at the end
        return [paths[i] for i in seen]
    if order == "Name A → Z":
        return sorted(paths, key=lambda p: natural_key(p.name))
    if order == "Name Z → A":
        return sorted(paths, key=lambda p: natural_key(p.name), reverse=True)
    return paths


def describe_inputs(files, order=ORDER_OPTIONS[0], custom="") -> str:
    """Numbered list of inputs (with page counts) shown under the upload box."""
    if not files:
        return "<span class='hint'>Add PDFs and/or images. They'll be combined in the order shown here.</span>"
    try:
        paths = order_paths(files, order, custom)
    except ValueError as e:
        return f"⚠️ {e}"
    lines = []
    total_pages = 0
    for i, p in enumerate(paths, 1):
        if p.suffix.lower() == ".pdf":
            try:
                reader = PdfReader(str(p))
                if reader.is_encrypted and not reader.decrypt(""):
                    info = "🔒 password protected"
                else:
                    n = len(reader.pages)
                    total_pages += n
                    info = f"{n} page{'s' * (n != 1)}"
            except Exception:
                info = "⚠️ unreadable"
            icon = "📄"
        else:
            total_pages += 1
            info, icon = "1 page", "🖼️"
        lines.append(f"{i}. {icon} `{p.name}` — {info} · {human_size(p.stat().st_size)}")
    lines.append(f"\n**Total: {total_pages} page(s)**")
    return "\n".join(lines)


def _jpeg_size_ok(obj) -> bool:
    """Only touch plain 8-bit images that JPEG can represent without losing masks."""
    if any(k in obj for k in ("/SMask", "/Mask", "/ImageMask", "/Decode")):
        return False
    return obj.get("/BitsPerComponent", 8) == 8


def compress_writer(writer: PdfWriter, quality: int, max_px: int, pages=None) -> int:
    """Re-encode images inside the PDF as JPEG at `quality`, capped to `max_px`.
    Only replaces an image when the new version is smaller. Returns images replaced."""
    replaced, seen = 0, set()
    page_list = writer.pages if pages is None else [writer.pages[i] for i in pages]
    for page in page_list:
        try:
            images = list(page.images)
        except Exception:
            continue
        for im in images:
            try:
                ref = im.indirect_reference
                if im.is_inline or ref is None or ref.idnum in seen:
                    continue
                seen.add(ref.idnum)
                obj = ref.get_object()
                if not _jpeg_size_ok(obj):
                    continue
                pil = im.image
                if pil.mode == "CMYK":
                    pil = pil.convert("RGB")
                if pil.mode not in ("RGB", "L"):
                    continue
                if max_px and max(pil.size) > max_px:
                    pil = pil.copy()
                    pil.thumbnail((max_px, max_px), Image.LANCZOS)
                buf = BytesIO()
                pil.save(buf, "JPEG", quality=quality, optimize=True)
                old_len = len(getattr(obj, "_data", b"") or b"")
                if old_len and buf.tell() >= old_len:
                    continue
                im.replace(pil, quality=quality, optimize=True)
                replaced += 1
            except Exception as exc:  # never fail the whole job for one odd image
                log.debug("Skipping image: %s", exc)
    return replaced


def _lossless_pass(writer: PdfWriter):
    for page in writer.pages:
        try:
            page.compress_content_streams()
        except Exception:
            pass
    try:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    except TypeError:  # older pypdf
        writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)


def _params_for(level: str):
    params = COMPRESSION_LEVELS.get(level)
    return None if params == "target" else params


def _fit_target(build, target_mb, progress=None):
    """Call build(params) with lighter → stronger settings until the result fits."""
    target = float(target_mb or 0) * 1024 * 1024
    if target <= 0:
        raise ValueError("Enter a target size greater than 0 MB.")
    steps = [None] + TARGET_STEPS
    data = None
    for i, params in enumerate(steps):
        if progress is not None:
            progress(i / len(steps), desc=f"Trying compression level {i + 1}/{len(steps)}…")
        data = build(params)
        if len(data) <= target:
            return data, None
    return data, (f"Couldn't get below {target_mb:g} MB — this is the smallest possible "
                  f"without making pages unreadable ({human_size(len(data))}).")


# ---------------------------------------------------------------------------
# Merge PDFs + images
# ---------------------------------------------------------------------------
def _image_page(path, page_mm, quality, max_px, margin_mm) -> PageObject:
    """One PDF page holding the image at `path`."""
    img = open_rgb(path)
    if max_px and max(img.size) > max_px:
        img.thumbnail((max_px, max_px), Image.LANCZOS)
    buf = BytesIO()
    if page_mm is None:
        # page takes the image's shape; long side is A4-long (297 mm)
        dpi = max(img.size) / (297 / 25.4)
        img.save(buf, "PDF", resolution=dpi, quality=quality)
        return PdfReader(buf).pages[0]

    img.save(buf, "PDF", resolution=72.0, quality=quality)
    src = PdfReader(buf).pages[0]
    iw, ih = float(src.mediabox.width), float(src.mediabox.height)
    pw, ph = page_mm[0] * PT_PER_MM, page_mm[1] * PT_PER_MM
    if (iw > ih) != (pw > ph):  # auto-rotate the page to match the image
        pw, ph = ph, pw
    m = max(0.0, float(margin_mm or 0)) * PT_PER_MM
    s = min((pw - 2 * m) / iw, (ph - 2 * m) / ih)
    if s <= 0:
        raise ValueError("margin is too large for the page")
    page = PageObject.create_blank_page(width=pw, height=ph)
    page.merge_transformed_page(src, Transformation().scale(s, s).translate((pw - iw * s) / 2, (ph - ih * s) / 2))
    return page


def _build_merged(paths, page_mm, margin, params, errors, progress=None) -> bytes:
    writer = PdfWriter()
    pdf_pages = []
    quality, max_px = params if params else (LOSSLESS_IMAGE_QUALITY, None)
    for i, p in enumerate(paths):
        if progress is not None:
            progress(i / max(len(paths), 1), desc=f"Adding {p.name}")
        try:
            if p.suffix.lower() == ".pdf":
                start = len(writer.pages)
                writer.append(_open_pdf(p))
                pdf_pages.extend(range(start, len(writer.pages)))
            else:
                writer.add_page(_image_page(p, page_mm, quality, max_px, margin))
        except Exception as exc:
            errors[p.name] = str(exc) or type(exc).__name__
    if not writer.pages:
        raise ValueError("None of the files could be added.")
    if params and pdf_pages:
        compress_writer(writer, quality, max_px, pdf_pages)
    _lossless_pass(writer)
    return _to_bytes(writer)


def merge_to_pdf(files, order, custom_order, page_size, margin, level, target_mb, progress=None):
    """Combine PDFs and images into one PDF. Returns (pdf_path, status_markdown)."""
    try:
        paths = order_paths(files, order, custom_order)
    except ValueError as e:
        return None, f"⚠️ {e}"
    if not paths:
        return None, "⚠️ Add at least one PDF or image."

    page_mm = PDF_PAGE_SIZES.get(page_size)
    t0 = time.time()
    errors, note = {}, None
    try:
        if COMPRESSION_LEVELS.get(level) == "target":
            data, note = _fit_target(
                lambda prm: _build_merged(paths, page_mm, margin, prm, errors), target_mb, progress)
        else:
            data = _build_merged(paths, page_mm, margin, _params_for(level), errors, progress)
    except ValueError as e:
        return None, f"⚠️ {e}" + _error_lines(errors)

    out = new_job_dir("merge_") / f"merged_{stamp()}.pdf"
    out.write_bytes(data)
    n_pages = len(PdfReader(BytesIO(data)).pages)
    status = (f"✅ **PDF ready** — {len(paths) - len(errors)} file(s) → **{n_pages} page(s)**, "
              f"**{human_size(len(data))}** ({time.time() - t0:.1f}s)")
    if note:
        status += f"\n\n⚠️ {note}"
    return str(out), status + _error_lines(errors)


def _error_lines(errors: dict) -> str:
    if not errors:
        return ""
    lines = [f"\n\n⚠️ Skipped {len(errors)} file(s):"]
    lines += [f"  • `{name}`: {msg}" for name, msg in list(errors.items())[:10]]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compress
# ---------------------------------------------------------------------------
def _compress_one(path, params) -> bytes:
    writer = PdfWriter(clone_from=_open_pdf(path))
    if params:
        compress_writer(writer, *params)
    _lossless_pass(writer)
    return _to_bytes(writer)


def compress_pdfs(files, level, target_mb, progress=None):
    """Compress each PDF. Returns (path_or_zip, status_markdown)."""
    paths = _supported([file_path(f) for f in files or []], PDF_EXTENSIONS)
    if not paths:
        return None, "⚠️ Add at least one PDF."

    job = new_job_dir("compress_")
    used, outputs, rows, errors = set(), [], [], {}
    t0 = time.time()
    for i, p in enumerate(paths):
        if progress is not None:
            progress(i / len(paths), desc=f"Compressing {p.name}")
        try:
            before = p.stat().st_size
            if COMPRESSION_LEVELS.get(level) == "target":
                data, note = _fit_target(lambda prm, src=p: _compress_one(src, prm), target_mb)
            else:
                data, note = _compress_one(p, _params_for(level)), None
            if len(data) >= before:
                data = p.read_bytes()
                note = "already as small as it gets – kept the original"
            out = job / unique_name(f"{p.stem}_compressed.pdf", used)
            out.write_bytes(data)
            outputs.append(out)
            saved = 100 * (1 - len(data) / before) if before else 0
            rows.append(f"| `{p.name}` | {human_size(before)} | **{human_size(len(data))}** | "
                        f"{saved:.0f}% | {note or ''} |")
        except Exception as exc:
            errors[p.name] = str(exc) or type(exc).__name__

    if not outputs:
        return None, "⚠️ Nothing could be compressed." + _error_lines(errors)
    table = "| File | Before | After | Saved | Note |\n|---|---|---|---|---|\n" + "\n".join(rows)
    status = f"✅ **Done** in {time.time() - t0:.1f}s\n\n{table}" + _error_lines(errors)
    if len(outputs) == 1:
        return str(outputs[0]), status
    return make_zip(outputs, job / f"compressed_{stamp()}.zip"), status


# ---------------------------------------------------------------------------
# Organize / split
# ---------------------------------------------------------------------------
def organize_pdf(file, mode, pages_text, rotate_text, angle):
    """Extract, remove, reorder, split and rotate pages. Returns (path, status)."""
    if not file:
        return None, "⚠️ Add a PDF."
    p = file_path(file[0] if isinstance(file, list) else file)
    try:
        reader = _open_pdf(p)
        n = len(reader.pages)
        angle = int(str(angle or 0).rstrip("°") or 0)
        rotate = set()
        if angle:
            groups = parse_ranges(rotate_text, n) if (rotate_text or "").strip() else [list(range(n))]
            rotate = {i for g in groups for i in g}

        if mode == ORGANIZE_MODES[3]:
            groups = [[i] for i in range(n)]
        else:
            groups = parse_ranges(pages_text, n)
            if not groups:
                if mode == ORGANIZE_MODES[0] and angle:
                    groups = [list(range(n))]  # just rotating
                else:
                    raise ValueError("Enter the pages, e.g. 1-3, 5, 8-end")
        if mode == ORGANIZE_MODES[1]:
            drop = {i for g in groups for i in g}
            groups = [[i for i in range(n) if i not in drop]]
            if not groups[0]:
                raise ValueError("That would remove every page.")
        elif mode == ORGANIZE_MODES[0]:
            groups = [[i for g in groups for i in g]]
    except Exception as e:
        return None, f"⚠️ {e}"

    def build(indices):
        writer = PdfWriter()
        for i in indices:
            page = writer.add_page(reader.pages[i])
            if i in rotate:
                page.rotate(angle)
        _lossless_pass(writer)
        return _to_bytes(writer)

    def label(g):
        a, b = g[0] + 1, g[-1] + 1
        return f"p{a}" if len(g) == 1 else f"p{a}-{b}"

    job = new_job_dir("organize_")
    if len(groups) == 1:
        out = job / f"{p.stem}_edited.pdf"
        out.write_bytes(build(groups[0]))
        return str(out), f"✅ **PDF ready** — {len(groups[0])} of {n} page(s)" + (
            f", rotated {len(rotate & set(groups[0]))} page(s) by {angle}°" if rotate else "")

    used, outs = set(), []
    for g in groups:
        out = job / unique_name(f"{p.stem}_{label(g)}.pdf", used)
        out.write_bytes(build(g))
        outs.append(out)
    return make_zip(outs, job / f"{p.stem}_split.zip"), f"✅ **Split into {len(outs)} PDFs** (ZIP)"


# ---------------------------------------------------------------------------
# PDF → images
# ---------------------------------------------------------------------------
def pdf_to_images(files, fmt_label, dpi, progress=None):
    """Render every page to an image. Returns (path_or_zip, previews, status)."""
    import pypdfium2 as pdfium

    paths = _supported([file_path(f) for f in files or []], PDF_EXTENSIONS)
    if not paths:
        return None, [], "⚠️ Add at least one PDF."
    fmt, ext = {"JPG": ("JPEG", ".jpg"), "PNG": ("PNG", ".png")}.get(fmt_label, ("JPEG", ".jpg"))
    dpi = max(36, min(600, int(dpi or 150)))

    job = new_job_dir("pdf2img_")
    used, outs, previews, errors = set(), [], [], {}
    t0 = time.time()
    for p in paths:
        try:
            doc = pdfium.PdfDocument(str(p))
        except Exception:
            errors[p.name] = "can't open – is it password protected? Unlock it first."
            continue
        try:
            n = len(doc)
            for i in range(n):
                if progress is not None:
                    progress(i / n, desc=f"{p.name}: page {i + 1}/{n}")
                page = doc[i]
                img = page.render(scale=dpi / 72).to_pil()
                page.close()
                if fmt == "JPEG" and img.mode != "RGB":
                    img = img.convert("RGB")
                out = job / unique_name(f"{p.stem}_page{i + 1:0{len(str(n))}d}{ext}", used)
                save_kw = {"quality": 92, "optimize": True} if fmt == "JPEG" else {"optimize": True}
                img.save(out, fmt, dpi=(dpi, dpi), **save_kw)
                outs.append(out)
                if len(previews) < 12:
                    thumb = img.copy()
                    thumb.thumbnail((600, 600))
                    previews.append((thumb, out.name))
        finally:
            doc.close()

    if not outs:
        return None, [], "⚠️ No pages were converted." + _error_lines(errors)
    status = f"✅ **{len(outs)} image(s)** at {dpi} DPI ({time.time() - t0:.1f}s)" + _error_lines(errors)
    if len(outs) == 1:
        return str(outs[0]), previews, status
    return make_zip(outs, job / f"pdf_pages_{stamp()}.zip"), previews, status


# ---------------------------------------------------------------------------
# Password protect / unlock
# ---------------------------------------------------------------------------
def protect_pdf(file, action, password, confirm=""):
    """Add or remove a password. Returns (path, status)."""
    if not file:
        return None, "⚠️ Add a PDF."
    p = file_path(file[0] if isinstance(file, list) else file)
    if not password:
        return None, "⚠️ Enter a password."
    try:
        reader = PdfReader(str(p))
        out_dir = new_job_dir("password_")
        if action.startswith("Add"):
            if confirm != password:
                return None, "⚠️ The two passwords don't match."
            if reader.is_encrypted:
                return None, "⚠️ This PDF already has a password. Remove it first."
            writer = PdfWriter(clone_from=reader)
            writer.encrypt(user_password=password, algorithm="AES-256")
            out = out_dir / f"{p.stem}_protected.pdf"
            msg = "🔒 **Password added** (AES-256). Keep the password safe — it can't be recovered."
        else:
            if not reader.is_encrypted:
                return None, "ℹ️ This PDF has no password."
            if not reader.decrypt(password):
                return None, "⚠️ Wrong password."
            writer = PdfWriter(clone_from=reader)
            out = out_dir / f"{p.stem}_unlocked.pdf"
            msg = "🔓 **Password removed.**"
        out.write_bytes(_to_bytes(writer))
        return str(out), msg
    except Exception as e:
        return None, f"⚠️ {e}"
