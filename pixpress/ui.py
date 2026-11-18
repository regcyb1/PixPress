"""Gradio user interface."""

import os
import threading

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")  # PixPress never phones home

import gradio as gr  # noqa: E402

from . import APP_NAME, __version__  # noqa: E402
from . import pdf_tools as pdf  # noqa: E402
from .common import log  # noqa: E402
from .imaging import (CPU_DEVICE, MAX_WORKERS, OUTPUT_FORMATS, PRESET_PPI,  # noqa: E402
                      PRESET_RESOLUTIONS, USE_PYVIPS, detect_devices, process_images)
from .passport import PAGE_SIZES, PHOTO_SIZES, describe_sheet_layout, make_passport_sheet  # noqa: E402

CUSTOM_CSS = """
.gradio-container { max-width: 1180px !important; margin: auto; }

#app-header {
    position: relative;
    text-align: center;
    padding: 26px 16px 18px;
    margin-bottom: 8px;
    border-radius: 18px;
    background: linear-gradient(135deg, rgba(102,126,234,.14), rgba(118,75,162,.14));
    border: 1px solid rgba(128,128,128,.18);
}
#app-header h1 {
    margin: 0;
    font-size: 2.4rem;
    font-weight: 800;
    letter-spacing: -.02em;
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
.primary-btn:hover { transform: translateY(-1px); box-shadow: 0 6px 18px rgba(102,126,234,.35); }
.status-box {
    min-height: 72px;
    padding: 10px 14px !important;
    border-radius: 12px;
    background: rgba(128,128,128,.06);
}
.info-box { padding: 10px 14px; border-radius: 12px; background: rgba(102,126,234,.08); }
#app-footer { display: flex; justify-content: space-between; align-items: center; opacity: .8; }
footer { display: none !important; }
"""

HINT = "<span class='hint'>{}</span>"


class card:  # noqa: N801 – reads like a layout block
    def __init__(self, title):
        self.title = title

    def __enter__(self):
        self.group = gr.Group(elem_classes="card")
        self.group.__enter__()
        gr.Markdown(f"### {self.title}", elem_classes="step-title")
        return self.group

    def __exit__(self, *exc):
        return self.group.__exit__(*exc)


def primary_button(label):
    return gr.Button(label, variant="primary", elem_classes="primary-btn", size="lg")


def status_box(text):
    return gr.Markdown(value=HINT.format(text), elem_classes="status-box")


def _quit():
    log.info("Quit requested from the UI.")
    threading.Timer(0.6, lambda: os._exit(0)).start()
    return gr.update(value=f"👋 {APP_NAME} has stopped. You can close this tab.", visible=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
def _resize_tab(devices):
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add images"):
                files = gr.File(label="Drop images here or click to browse",
                                file_types=["image"], file_count="multiple", height=180)
            with card("2 · Choose size"):
                res = gr.Dropdown(list(PRESET_RESOLUTIONS), value="1024 × 1024", label="Output size")
                with gr.Row(visible=False) as custom_row:
                    cw = gr.Number(value=1024, label="Width (px)", precision=0, minimum=1, maximum=16384)
                    ch = gr.Number(value=1024, label="Height (px)", precision=0, minimum=1, maximum=16384)
                aspect = gr.Checkbox(value=True, label="Keep proportions (fit inside the size, no stretching)")
            with card("3 · Format & file size"):
                with gr.Row():
                    fmt = gr.Radio(list(OUTPUT_FORMATS), value="JPG", label="Save as",
                                   info="PNG/WebP keep transparency")
                    max_kb = gr.Number(value=0, label="Max file size (KB)", precision=0, minimum=0,
                                       info="0 = no limit · e.g. 200 for online forms")
                with gr.Row():
                    ppi = gr.Radio(list(PRESET_PPI), value="300", label="PPI / DPI", info="72 = screen · 300 = print")
                    cppi = gr.Number(value=300, label="Custom PPI", precision=0, minimum=1, maximum=2400, visible=False)
            with gr.Accordion("⚙️ Advanced options", open=False):
                quality = gr.Slider(30, 100, step=1, value=90, label="Quality (JPG / WebP)",
                                    info="Higher = better quality, bigger files")
                device = gr.Dropdown(list(devices), value=devices[0], label="Compute device",
                                     info="GPU options appear when PyTorch is installed")
        with gr.Column(scale=5):
            with card("4 · Resize & download"):
                btn = primary_button("⚡ Resize Images")
                status = status_box("Add images, choose a size, then click <b>Resize Images</b>.")
                out = gr.File(label="📥 Download result", interactive=False)
                clear = gr.Button("🧹 Clear", variant="secondary", size="sm")

    def on_res(preset):
        if preset == "Custom":
            return gr.update(visible=True), gr.update(), gr.update()
        w, h = PRESET_RESOLUTIONS[preset]
        return gr.update(visible=False), gr.update(value=w), gr.update(value=h)

    res.change(on_res, [res], [custom_row, cw, ch])
    ppi.change(lambda p: gr.update(visible=True) if p == "Custom" else gr.update(value=PRESET_PPI[p], visible=False),
               [ppi], [cppi])

    def run(f, r, w, h, a, p, cp, q, d, fm, mk, progress=gr.Progress()):
        path, msg = process_images(f, r, w, h, a, p, cp, q, d, progress, fm, mk)
        return msg, path

    btn.click(run, [files, res, cw, ch, aspect, ppi, cppi, quality, device, fmt, max_kb], [status, out])
    clear.click(lambda: (None, None, HINT.format("Cleared. Add new images to start again.")),
                outputs=[files, out, status])


def _passport_tab():
    gr.Markdown(HINT.format("Add one or more photos — each one is printed several times "
                            "on a sheet you can print at home and cut out."))
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add photos"):
                files = gr.File(label="Drop photos here (multiple allowed)", file_types=["image"],
                                file_count="multiple", height=160)
                gallery = gr.Gallery(columns=6, height=150, object_fit="cover", show_label=False, visible=False)
            with card("2 · Photo size & copies"):
                size = gr.Dropdown(list(PHOTO_SIZES), value=next(iter(PHOTO_SIZES)), label="Photo size")
                with gr.Row(visible=False) as custom_row:
                    cw = gr.Number(value=35, label="Width (mm)", minimum=5, maximum=300)
                    ch = gr.Number(value=45, label="Height (mm)", minimum=5, maximum=300)
                copies = gr.Slider(1, 30, step=1, value=2, label="Copies of each photo")
            with card("3 · Paper"):
                with gr.Row():
                    page = gr.Dropdown(list(PAGE_SIZES), value=next(iter(PAGE_SIZES)), label="Page size")
                    orient = gr.Radio(["Portrait", "Landscape"], value="Portrait", label="Orientation")
            with gr.Accordion("⚙️ Layout options", open=False):
                with gr.Row():
                    margin = gr.Number(value=5, label="Page margin (mm)", minimum=0, maximum=50,
                                       info="Most home printers need ≥ 5 mm")
                    gap = gr.Number(value=3, label="Space between photos (mm)", minimum=0, maximum=30)
                fit = gr.Radio(["Crop to fill (recommended)", "Fit whole photo (white bars)"],
                               value="Crop to fill (recommended)", label="If the photo shape doesn't match")
                with gr.Row():
                    keep = gr.Checkbox(value=True, label="Don't split a photo's copies across pages")
                    guides = gr.Checkbox(value=True, label="Draw cutting guides")
        with gr.Column(scale=5):
            with card("4 · Create PDF"):
                info = gr.Markdown(elem_classes="info-box")
                btn = primary_button("🖨️ Create Printable PDF")
                status = status_box("Your PDF and a page preview will appear here.")
                out = gr.File(label="📥 Download PDF", interactive=False)
                preview = gr.Gallery(label="Page preview", columns=1, height=520, object_fit="contain", preview=True)

    size.change(lambda p: gr.update(visible=(p == "Custom")), [size], [custom_row])
    files.change(lambda f: gr.update(value=[str(x) for x in f], visible=True) if f else gr.update(value=None, visible=False),
                 [files], [gallery])
    layout_inputs = [size, cw, ch, page, orient, margin, gap, copies, files]
    for comp in layout_inputs:
        comp.change(describe_sheet_layout, layout_inputs, [info])

    def run(f, s, w, h, pg, o, c, m, g, ft, k, gd, progress=gr.Progress()):
        path, previews, msg = make_passport_sheet(f, s, w, h, pg, o, c, m, g, ft, k, gd, progress)
        return msg, path, previews

    btn.click(run, [files, size, cw, ch, page, orient, copies, margin, gap, fit, keep, guides],
              [status, out, preview])
    return layout_inputs, info


def _compression_inputs(default="Balanced – recommended"):
    level = gr.Radio(list(pdf.COMPRESSION_LEVELS), value=default, label="Compression")
    target = gr.Number(value=2, label="Target size (MB)", minimum=0.05, step=0.1, visible=False,
                       info="Tries lighter settings first, stops as soon as the file fits")
    level.change(lambda lv: gr.update(visible=(pdf.COMPRESSION_LEVELS.get(lv) == "target")), [level], [target])
    return level, target


def _merge_subtab():
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add PDFs and/or images"):
                files = gr.File(label="Drop PDFs, JPG, PNG, WebP, TIFF… (any mix)",
                                file_types=[".pdf", "image"], file_count="multiple", height=170)
                with gr.Row():
                    order = gr.Dropdown(pdf.ORDER_OPTIONS, value=pdf.ORDER_OPTIONS[0], label="Order")
                    custom = gr.Textbox(label="Custom order (optional)", placeholder="e.g. 3, 1, 2")
                listing = gr.Markdown(pdf.describe_inputs(None), elem_classes="info-box")
            with card("2 · Image pages"):
                with gr.Row():
                    page_size = gr.Dropdown(list(pdf.PDF_PAGE_SIZES), value="A4", label="Page size for images",
                                            info="PDF pages keep their own size")
                    margin = gr.Number(value=10, label="Margin (mm)", minimum=0, maximum=50)
            with card("3 · File size"):
                level, target = _compression_inputs()
        with gr.Column(scale=5):
            with card("4 · Merge"):
                btn = primary_button("📎 Create PDF")
                status = status_box("Your combined PDF will appear here.")
                out = gr.File(label="📥 Download PDF", interactive=False)

    for comp in (files, order, custom):
        comp.change(pdf.describe_inputs, [files, order, custom], [listing])

    def run(f, o, c, ps, m, lv, t, progress=gr.Progress()):
        path, msg = pdf.merge_to_pdf(f, o, c, ps, m, lv, t, progress)
        return msg, path

    btn.click(run, [files, order, custom, page_size, margin, level, target], [status, out])


def _compress_subtab():
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add PDFs"):
                files = gr.File(label="Drop one or more PDFs", file_types=[".pdf"], file_count="multiple", height=170)
            with card("2 · How small?"):
                level, target = _compression_inputs()
                gr.Markdown(HINT.format("Compression shrinks photos and scans inside the PDF. "
                                        "Text and vector graphics stay sharp."))
        with gr.Column(scale=5):
            with card("3 · Compress"):
                btn = primary_button("🗜️ Compress PDF")
                status = status_box("Before/after sizes will appear here.")
                out = gr.File(label="📥 Download", interactive=False)

    def run(f, lv, t, progress=gr.Progress()):
        path, msg = pdf.compress_pdfs(f, lv, t, progress)
        return msg, path

    btn.click(run, [files, level, target], [status, out])


def _organize_subtab():
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add a PDF"):
                file = gr.File(label="Drop a PDF", file_types=[".pdf"], file_count="single", height=150)
                listing = gr.Markdown(elem_classes="info-box", visible=False)
            with card("2 · What to do"):
                mode = gr.Radio(pdf.ORGANIZE_MODES, value=pdf.ORGANIZE_MODES[0], label="Action")
                pages = gr.Textbox(label="Pages", placeholder="e.g. 1-3, 5, 8-end   (3,1,2 reorders)",
                                   info="Commas separate ranges. 'end' means the last page.")
            with card("3 · Rotate (optional)"):
                with gr.Row():
                    angle = gr.Radio(["0°", "90°", "180°", "270°"], value="0°", label="Rotate clockwise")
                    rot_pages = gr.Textbox(label="Pages to rotate", placeholder="blank = all pages",
                                           info="Original page numbers")
        with gr.Column(scale=5):
            with card("4 · Apply"):
                btn = primary_button("✂️ Create PDF")
                status = status_box("Split results download as a ZIP.")
                out = gr.File(label="📥 Download", interactive=False)

    file.change(lambda f: gr.update(value=pdf.describe_inputs([f]), visible=True) if f else gr.update(visible=False),
                [file], [listing])
    mode.change(lambda m: gr.update(interactive=(m != pdf.ORGANIZE_MODES[3])), [mode], [pages])

    def run(f, m, pg, rp, a):
        path, msg = pdf.organize_pdf(f, m, pg, rp, a)
        return msg, path

    btn.click(run, [file, mode, pages, rot_pages, angle], [status, out])


def _to_images_subtab():
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add PDFs"):
                files = gr.File(label="Drop one or more PDFs", file_types=[".pdf"], file_count="multiple", height=150)
            with card("2 · Image settings"):
                with gr.Row():
                    fmt = gr.Radio(["JPG", "PNG"], value="JPG", label="Format")
                    dpi = gr.Slider(72, 600, step=1, value=150, label="Resolution (DPI)",
                                    info="150 = screen · 300 = print")
        with gr.Column(scale=5):
            with card("3 · Convert"):
                btn = primary_button("🖼️ Convert to Images")
                status = status_box("Every page becomes one image.")
                out = gr.File(label="📥 Download", interactive=False)
                preview = gr.Gallery(label="Preview", columns=3, height=320, object_fit="contain")

    def run(f, fm, d, progress=gr.Progress()):
        path, previews, msg = pdf.pdf_to_images(f, fm, d, progress)
        return msg, path, previews

    btn.click(run, [files, fmt, dpi], [status, out, preview])


def _password_subtab():
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add a PDF"):
                file = gr.File(label="Drop a PDF", file_types=[".pdf"], file_count="single", height=150)
            with card("2 · Password"):
                action = gr.Radio(["Add password", "Remove password"], value="Add password", label="Action")
                with gr.Row():
                    pw = gr.Textbox(label="Password", type="password")
                    pw2 = gr.Textbox(label="Confirm password", type="password")
        with gr.Column(scale=5):
            with card("3 · Apply"):
                btn = primary_button("🔐 Apply")
                status = status_box("Removing a password needs the current password.")
                out = gr.File(label="📥 Download", interactive=False)

    action.change(lambda a: gr.update(visible=a.startswith("Add")), [action], [pw2])

    def run(f, a, p, p2):
        path, msg = pdf.protect_pdf(f, a, p, p2)
        return msg, path

    btn.click(run, [file, action, pw, pw2], [status, out])


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
def build_ui():
    """Return (blocks, theme, css)."""
    theme = gr.themes.Soft(primary_hue="indigo", secondary_hue="purple", neutral_hue="slate", radius_size="lg")
    devices = detect_devices()
    backend = "pyvips" if USE_PYVIPS else "Pillow"
    gpu = [d for d in devices if d != CPU_DEVICE and "CPU" not in d]
    badges = [f"⚙️ {backend}", f"🧵 {MAX_WORKERS} workers"] + [f"🚀 {d}" for d in gpu] + ["🔒 100% offline"]

    with gr.Blocks(title=APP_NAME, analytics_enabled=False) as app:
        gr.HTML(f"""
            <div id="app-header">
              <h1>{APP_NAME}</h1>
              <p>Resize photos, print passport sheets and work with PDFs — everything stays on your computer.</p>
              <div class="badges">{''.join(f"<span class='badge'>{b}</span>" for b in badges)}</div>
            </div>""")

        with gr.Tabs():
            with gr.Tab("🖼️ Bulk Resize"):
                _resize_tab(devices)
            with gr.Tab("🪪 Passport Photos"):
                layout_inputs, layout_info = _passport_tab()
            with gr.Tab("📄 PDF Tools"):
                with gr.Tabs():
                    with gr.Tab("📎 Merge & Images → PDF"):
                        _merge_subtab()
                    with gr.Tab("🗜️ Compress"):
                        _compress_subtab()
                    with gr.Tab("✂️ Split & Organize"):
                        _organize_subtab()
                    with gr.Tab("🖼️ PDF → Images"):
                        _to_images_subtab()
                    with gr.Tab("🔐 Password"):
                        _password_subtab()

        with gr.Row(elem_id="app-footer"):
            gr.Markdown(HINT.format(f"{APP_NAME} v{__version__} · runs locally, files never leave this computer"))
            quit_btn = gr.Button("⏻ Quit app", variant="stop", size="sm", scale=0, min_width=110)
        bye = gr.Markdown(visible=False)
        quit_btn.click(_quit, outputs=[bye])

        app.load(describe_sheet_layout, layout_inputs, [layout_info])

    return app, theme, CUSTOM_CSS


def launch():
    host = os.environ.get("PIXPRESS_HOST", "127.0.0.1")  # set 0.0.0.0 to use from other devices on your network
    port = os.environ.get("PIXPRESS_PORT")
    app, theme, css = build_ui()
    log.info("Starting %s v%s on http://%s:%s", APP_NAME, __version__, host, port or "7860+")
    app.launch(
        server_name=host,
        server_port=int(port) if port else None,  # None → first free port from 7860
        inbrowser=True,
        theme=theme,
        css=css,
    )
