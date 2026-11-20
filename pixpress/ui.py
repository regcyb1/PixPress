"""Gradio user interface."""

import os
import threading
from pathlib import Path

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")  # PixPress never phones home

import gradio as gr  # noqa: E402

from . import APP_NAME, __version__  # noqa: E402
from . import pdf_tools as pdf  # noqa: E402
from .common import log  # noqa: E402
from .imaging import (CPU_DEVICE, MAX_WORKERS, OUTPUT_FORMATS, PRESET_PPI,  # noqa: E402
                      PRESET_RESOLUTIONS, USE_PYVIPS, detect_devices, process_images)
from .passport import (PAGE_SIZES, PHOTO_SIZES, cropped_thumbnail, cropper_value,  # noqa: E402
                       describe_crop, describe_sheet_layout, expand_inputs, is_cropped,
                       make_passport_sheet, normalize_crop)

CUSTOM_CSS = """
/* ---------- page ---------- */
.gradio-container { max-width: 1200px !important; margin: auto; padding-top: 18px !important; }
footer { display: none !important; }

/* ---------- header ---------- */
#app-header {
    display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
    padding: 18px 22px; margin-bottom: 6px; border-radius: 20px;
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 55%, #a855f7 100%);
    color: #fff; box-shadow: 0 10px 30px -12px rgba(79,70,229,.55);
}
#app-header .brand { display: flex; align-items: center; gap: 14px; }
#app-header .logo {
    width: 46px; height: 46px; border-radius: 14px; display: grid; place-items: center;
    background: rgba(255,255,255,.18); border: 1px solid rgba(255,255,255,.3); font-size: 24px;
}
#app-header h1 { margin: 0; font-size: 1.6rem; font-weight: 800; letter-spacing: -.02em; color: #fff; }
#app-header p { margin: 2px 0 0; font-size: .92rem; opacity: .88; color: #fff; }
.badges { display: flex; gap: 6px; flex-wrap: wrap; }
.badge {
    font-size: .75rem; font-weight: 600; padding: 5px 10px; border-radius: 999px; color: #fff;
    background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
}

/* ---------- tabs ---------- */
.tab-wrapper { height: auto !important; overflow: visible !important; }
.tab-container { height: auto !important; overflow: visible !important; gap: 6px; border-bottom: none !important; padding: 6px 0 10px; flex-wrap: wrap; }
.tab-container button[role=tab] {
    border-radius: 999px !important; padding: 10px 20px !important; font-weight: 600; font-size: .95rem !important;
    height: auto !important; line-height: 1.2 !important;
    border: 1px solid var(--border-color-primary) !important; background: var(--background-fill-primary);
}
.tab-container button[role=tab].selected {
    color: #fff !important; border-color: transparent !important;
    background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
}
.tab-container button[role=tab].selected::after { display: none !important; }

/* ---------- cards ---------- */
.card {
    background: var(--background-fill-primary) !important;
    border: 1px solid var(--border-color-primary) !important;
    border-radius: 18px !important; padding: 16px 16px 14px !important;
    box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 8px 24px -16px rgba(15,23,42,.18);
    gap: 12px !important;
}
.step-title h3 { display: flex; align-items: center; gap: 10px; margin: 0 !important;
                 font-size: 1.02rem !important; font-weight: 700 !important; }
.step-num {
    width: 26px; height: 26px; border-radius: 50%; display: inline-grid; place-items: center; flex: none;
    font-size: .8rem; font-weight: 800; color: #fff; background: linear-gradient(135deg, #4f46e5, #7c3aed);
}
.card > .block, .card .block { box-shadow: none !important; }
.card .form { border: none !important; background: transparent !important; gap: 12px !important; }

/* accordions styled like cards */
.gradio-container .accordion-card {
    background: var(--background-fill-primary) !important;
    border: 1px solid var(--border-color-primary) !important; border-radius: 18px !important;
    box-shadow: 0 1px 2px rgba(15,23,42,.04), 0 8px 24px -16px rgba(15,23,42,.18);
}
.gradio-container .accordion-card { padding: 14px 16px !important; }
.accordion-card > button span { font-weight: 700 !important; font-size: 1rem; }

/* ---------- upload areas ---------- */
.card .block:has(.upload-container), .card .block:has(.file-preview) {
    border: 2px dashed rgba(99,102,241,.45) !important; border-radius: 14px !important;
    background: rgba(99,102,241,.04) !important;
}
.upload-container:hover { background: rgba(99,102,241,.07); }

/* ---------- buttons & status ---------- */
.primary-btn {
    background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important;
    color: #fff !important; font-weight: 700 !important; font-size: 1.05rem !important;
    border: none !important; border-radius: 14px !important; min-height: 52px;
    box-shadow: 0 8px 20px -10px rgba(79,70,229,.8);
    transition: transform .15s ease, box-shadow .15s ease, filter .15s ease;
}
.primary-btn:hover { transform: translateY(-1px); filter: brightness(1.06);
                     box-shadow: 0 12px 26px -10px rgba(79,70,229,.9); }
.status-box { min-height: 64px; padding: 12px 14px !important; border-radius: 12px;
              background: var(--background-fill-secondary) !important; }
.info-box { padding: 10px 14px !important; border-radius: 12px;
            background: rgba(99,102,241,.08) !important; border: 1px solid rgba(99,102,241,.18) !important; }
.hint { opacity: .72; font-size: .88rem; }
.sticky-col { position: sticky; top: 12px; align-self: flex-start; }

/* ---------- footer ---------- */
#app-footer { display: flex; justify-content: space-between; align-items: center; opacity: .85; margin-top: 8px; }

@media (max-width: 760px) {
    #app-header { padding: 14px 16px; }
    .sticky-col { position: static; }
}
"""

HINT = "<span class='hint'>{}</span>"


class card:  # noqa: N801 – reads like a layout block
    def __init__(self, title):
        self.title = title

    def __enter__(self):
        self.group = gr.Column(elem_classes="card")
        self.group.__enter__()
        num, _, text = self.title.partition(" · ")
        title = f"<span class='step-num'>{num}</span>{text}" if text and num.isdigit() else self.title
        gr.Markdown(f"### {title}", elem_classes="step-title")
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
# Drag-to-crop widget (plain HTML/JS, works offline)
# ---------------------------------------------------------------------------
CROPPER_HTML = """${value && value.src ? `
<div class="ppc-stage">
  <div class="ppc-wrap" data-aspect="${value.aspect}" data-iw="${value.iw}" data-ih="${value.ih}" data-box="${value.box}">
    <img src="${value.src}" draggable="false" alt="photo to crop"/>
    <div class="ppc-box">
      <div class="ppc-oval"></div>
      <span class="ppc-tag">Printed area</span>
      <i class="ppc-h" data-c="tl"></i><i class="ppc-h" data-c="tr"></i>
      <i class="ppc-h" data-c="bl"></i><i class="ppc-h" data-c="br"></i>
    </div>
  </div>
</div>` : `<div class="ppc-empty">Add photos above to start cropping</div>`}"""

CROPPER_CSS = """
.ppc-stage { display:flex; justify-content:center; padding:10px; border-radius:12px; background:rgba(0,0,0,.35); }
.ppc-wrap { position:relative; display:inline-block; overflow:hidden; touch-action:none; user-select:none; line-height:0; }
.ppc-wrap img { display:block; max-width:100%; max-height:460px; pointer-events:none; }
.ppc-box { position:absolute; box-shadow:0 0 0 9999px rgba(0,0,0,.58); outline:2px solid #fff; cursor:move; }
.ppc-oval { position:absolute; left:22%; top:12%; width:56%; height:60%; border:2px dashed rgba(140,160,255,.95);
            border-radius:50%; pointer-events:none; }
.ppc-tag { position:absolute; left:4px; top:4px; font:600 11px/1.5 sans-serif; color:#fff; padding:0 6px;
           border-radius:4px; background:rgba(102,126,234,.92); pointer-events:none; }
.ppc-h { position:absolute; width:20px; height:20px; border:4px solid #fff; }
.ppc-h[data-c=tl] { left:-2px; top:-2px; border-right:0; border-bottom:0; cursor:nwse-resize; }
.ppc-h[data-c=tr] { right:-2px; top:-2px; border-left:0; border-bottom:0; cursor:nesw-resize; }
.ppc-h[data-c=bl] { left:-2px; bottom:-2px; border-right:0; border-top:0; cursor:nesw-resize; }
.ppc-h[data-c=br] { right:-2px; bottom:-2px; border-left:0; border-top:0; cursor:nwse-resize; }
.ppc-h::after { content:''; position:absolute; inset:-12px; }  /* bigger grab area */
.ppc-empty { padding:40px 10px; text-align:center; opacity:.6; border:1px dashed rgba(128,128,128,.4); border-radius:12px; }
"""

CROPPER_JS = """
let drag = null;
const wrapEl = () => element.querySelector('.ppc-wrap');
const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
function setBox(w, b) {
  const el = w.querySelector('.ppc-box');
  el.style.left = (b[0] * 100) + '%'; el.style.top = (b[1] * 100) + '%';
  el.style.width = (b[2] * 100) + '%'; el.style.height = (b[3] * 100) + '%';
  el.dataset.box = b.map(v => v.toFixed(5)).join(',');
}
function ratio(w) { return (+w.dataset.iw) / ((+w.dataset.ih) * (+w.dataset.aspect)); }  // height = width * ratio
function init() { const w = wrapEl(); if (w) setBox(w, w.dataset.box.split(',').map(Number)); }
init();
watch('value', init);

element.addEventListener('pointerdown', (e) => {
  const w = wrapEl(); if (!w) return;
  const box = w.querySelector('.ppc-box');
  if (!box.contains(e.target)) return;
  e.preventDefault();
  drag = { mode: e.target.dataset.c || 'move', x: e.clientX, y: e.clientY, w, k: ratio(w),
           W: w.clientWidth, H: w.clientHeight, b: box.dataset.box.split(',').map(Number) };
});
window.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const d = drag, dx = (e.clientX - d.x) / d.W, dy = (e.clientY - d.y) / d.H;
  let [l, t, bw, bh] = d.b;
  if (d.mode === 'move') {
    l = clamp(l + dx, 0, 1 - bw); t = clamp(t + dy, 0, 1 - bh);
  } else {
    const left = d.mode[1] === 'l', top = d.mode[0] === 't';
    const ax = left ? l + bw : l, ay = top ? t + bh : t;           // opposite corner stays put
    let nw = Math.max(bw + (left ? -dx : dx), (bh + (top ? -dy : dy)) / d.k);
    const maxW = Math.min(left ? ax : 1 - ax, (top ? ay : 1 - ay) / d.k);
    nw = clamp(nw, Math.min(0.04, maxW), maxW);
    bw = nw; bh = nw * d.k;
    l = left ? ax - bw : ax; t = top ? ay - bh : ay;
  }
  setBox(d.w, [l, t, bw, bh]);
});
window.addEventListener('pointerup', () => { drag = null; });
element.addEventListener('wheel', (e) => {             // mouse wheel / trackpad resizes the box
  const w = wrapEl(); if (!w || !w.querySelector('.ppc-box').contains(e.target)) return;
  e.preventDefault();
  const k = ratio(w);
  let [l, t, bw, bh] = w.querySelector('.ppc-box').dataset.box.split(',').map(Number);
  const cx = l + bw / 2, cy = t + bh / 2;
  bw = clamp(bw * (e.deltaY < 0 ? 0.96 : 1.04), 0.04, Math.min(1, 1 / k)); bh = bw * k;
  setBox(w, [clamp(cx - bw / 2, 0, 1 - bw), clamp(cy - bh / 2, 0, 1 - bh), bw, bh]);
}, { passive: false });
"""

# Reads the box from the widget so the Save button can send it to Python.
READ_CROP_BOX_JS = """(...args) => {
  const el = document.querySelector('#pp-cropper .ppc-box');
  args[args.length - 1] = el ? el.dataset.box : '';
  return args;
}"""


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
            with gr.Accordion("⚙️ Advanced options", open=False, elem_classes="accordion-card"):
                quality = gr.Slider(30, 100, step=1, value=90, label="Quality (JPG / WebP)",
                                    info="Higher = better quality, bigger files")
                device = gr.Dropdown(list(devices), value=devices[0], label="Compute device",
                                     info="GPU options appear when PyTorch is installed")
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("4 · Resize & download"):
                btn = primary_button("⚡ Resize Images")
                status = status_box("Add images, choose a size, then click <b>Resize Images</b>.")
                out = gr.File(label="📥 Download result", interactive=False, height=120)
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


def _photo_label(i, path):
    return f"{i + 1}. {Path(path).name}"


def _passport_tab():
    gr.Markdown(HINT.format("Add photos or PDFs — each photo is printed several times "
                            "on a sheet you can print at home and cut out."))
    photos = gr.State([])   # image paths (PDF pages already turned into images)
    crops = gr.State({})    # image path -> crop settings
    with gr.Row(equal_height=False):
        with gr.Column(scale=6):
            with card("1 · Add photos"):
                files = gr.File(label="Drop photos or PDFs here (multiple allowed)",
                                file_types=["image", ".pdf"], file_count="multiple", height=160)
                gallery = gr.Gallery(columns=6, height=150, object_fit="cover", show_label=False,
                                     visible=False, allow_preview=False)
                load_msg = gr.Markdown(visible=False)
            with card("✂️ Crop photos (optional)"):
                gr.Markdown(HINT.format("Pick a photo (or click its thumbnail). <b>Drag the box</b> to move it, "
                                        "drag a <b>corner</b> (or scroll) to resize. Only what's inside the box "
                                        "is printed — keep the face in the oval, then click <b>💾 Save crop</b>."))
                pick = gr.Dropdown([], label="Photo to crop", interactive=True)
                cropper = gr.HTML(value=cropper_value(None, None, 0, 0), html_template=CROPPER_HTML,
                                  css_template=CROPPER_CSS, js_on_load=CROPPER_JS, elem_id="pp-cropper")
                box_txt = gr.Textbox(visible=False)
                with gr.Row():
                    save_crop = gr.Button("💾 Save crop", variant="primary", size="sm")
                    rotate = gr.Button("↻ Rotate 90°", size="sm")
                    reset = gr.Button("↺ Reset", size="sm")
                crop_msg = gr.Markdown(elem_classes="info-box")
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
            with gr.Accordion("⚙️ Layout options", open=False, elem_classes="accordion-card"):
                with gr.Row():
                    margin = gr.Number(value=5, label="Page margin (mm)", minimum=0, maximum=50,
                                       info="Most home printers need ≥ 5 mm")
                    gap = gr.Number(value=3, label="Space between photos (mm)", minimum=0, maximum=30)
                fit = gr.Radio(["Crop to fill (recommended)", "Fit whole photo (white bars)"],
                               value="Crop to fill (recommended)", label="If the photo shape doesn't match")
                with gr.Row():
                    keep = gr.Checkbox(value=True, label="Don't split a photo's copies across pages")
                    guides = gr.Checkbox(value=True, label="Draw cutting guides")
                trim = gr.Checkbox(value=True, label="PDFs: trim white page borders automatically")
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("4 · Create PDF"):
                info = gr.Markdown(elem_classes="info-box")
                btn = primary_button("🖨️ Create Printable PDF")
                status = status_box("Your PDF and a page preview will appear here.")
                out = gr.File(label="📥 Download PDF", interactive=False, visible=False)
                preview = gr.Gallery(label="Page preview", columns=1, height=520, object_fit="contain",
                                     preview=True, visible=False)

    size.change(lambda p: gr.update(visible=(p == "Custom")), [size], [custom_row])

    # --- loading photos (PDF pages become photos) ---
    def gallery_items(paths, cr, s, w, h):
        items = []
        for x in paths:
            if is_cropped(cr.get(x)):
                items.append((cropped_thumbnail(x, s, w, h, cr[x]), "✂️ cropped"))
            else:
                items.append((x, None))
        return gr.update(value=items or None, visible=bool(items))

    def on_files(f, auto_trim, s, w, h):
        paths, errors = expand_inputs(f, auto_trim)
        paths = [str(x) for x in paths]
        labels = [_photo_label(i, x) for i, x in enumerate(paths)]
        msg = ""
        n_pdf = sum(1 for x in (f or []) if str(x).lower().endswith(".pdf"))
        if n_pdf:
            msg = HINT.format(f"📄 {n_pdf} PDF(s) turned into photos — check them below and crop if needed.")
        if errors:
            msg += "\n\n⚠️ " + "\n\n⚠️ ".join(errors)
        first = paths[0] if paths else None
        return (paths, {}, gallery_items(paths, {}, s, w, h),
                gr.update(value=msg, visible=bool(msg)),
                gr.update(choices=labels, value=labels[0] if labels else None),
                cropper_value(first, s, w, h), describe_crop(first, s, w, h, None, saved=False))

    load_outputs = [photos, crops, gallery, load_msg, pick, cropper, crop_msg]
    files.change(on_files, [files, trim, size, cw, ch], load_outputs)
    trim.change(on_files, [files, trim, size, cw, ch], load_outputs)

    # --- cropping ---
    def _current(label, paths):
        if not label or not paths:
            return None
        try:
            return paths[int(label.split(".", 1)[0]) - 1]
        except (ValueError, IndexError):
            return None

    def show(label, paths, cr, s, w, h):
        path = _current(label, paths)
        return (cropper_value(path, s, w, h, cr.get(path)),
                describe_crop(path, s, w, h, cr.get(path), saved=is_cropped(cr.get(path))))

    def on_save(label, paths, cr, s, w, h, box):
        path = _current(label, paths)
        if path is None:
            return cr, gr.update(), "⚠️ Add a photo first."
        try:
            box = tuple(float(v) for v in str(box).split(","))
        except ValueError:
            box = None
        c = normalize_crop({**(cr.get(path) or {}), "box": box})
        cr = {**cr, path: c}
        return cr, gallery_items(paths, cr, s, w, h), describe_crop(path, s, w, h, c, saved=True)

    def on_rotate(label, paths, cr, s, w, h):
        path = _current(label, paths)
        if path is None:
            return cr, gr.update(), gr.update(), gr.update()
        c = normalize_crop(cr.get(path))
        cr = {**cr, path: {"rotate": (c["rotate"] + 90) % 360, "box": None}}
        return (cr, gallery_items(paths, cr, s, w, h), *show(label, paths, cr, s, w, h))

    def on_reset(label, paths, cr, s, w, h):
        path = _current(label, paths)
        cr = {k: v for k, v in cr.items() if k != path}
        return (cr, gallery_items(paths, cr, s, w, h), *show(label, paths, cr, s, w, h))

    def on_gallery_select(paths, evt: gr.SelectData):
        if not paths or evt.index is None:
            return gr.update()
        i = evt.index if isinstance(evt.index, int) else evt.index[0]
        return gr.update(value=_photo_label(i, paths[i]))

    size_inputs = [size, cw, ch]
    crop_in = [pick, photos, crops] + size_inputs
    pick.change(show, crop_in, [cropper, crop_msg])
    save_crop.click(on_save, crop_in + [box_txt], [crops, gallery, crop_msg], js=READ_CROP_BOX_JS)
    rotate.click(on_rotate, crop_in, [crops, gallery, cropper, crop_msg])
    reset.click(on_reset, crop_in, [crops, gallery, cropper, crop_msg])
    gallery.select(on_gallery_select, [photos], [pick])
    for comp in size_inputs:  # new photo shape → new box shape and thumbnails
        comp.change(lambda l, p, c, s, w, h: (*show(l, p, c, s, w, h), gallery_items(p, c, s, w, h)),
                    crop_in, [cropper, crop_msg, gallery], show_progress="hidden")

    # --- layout summary & PDF ---
    layout_inputs = [size, cw, ch, page, orient, margin, gap, copies, photos]
    for comp in layout_inputs:
        comp.change(describe_sheet_layout, layout_inputs, [info])

    def run(f, s, w, h, pg, o, c, m, g, ft, k, gd, cr, progress=gr.Progress()):
        path, previews, msg = make_passport_sheet(f, s, w, h, pg, o, c, m, g, ft, k, gd, progress, crops=cr)
        return msg, gr.update(value=path, visible=bool(path)), gr.update(value=previews, visible=bool(previews))

    btn.click(run, [photos, size, cw, ch, page, orient, copies, margin, gap, fit, keep, guides, crops],
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
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("4 · Merge"):
                btn = primary_button("📎 Create PDF")
                status = status_box("Your combined PDF will appear here.")
                out = gr.File(label="📥 Download PDF", interactive=False, height=120)

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
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("3 · Compress"):
                btn = primary_button("🗜️ Compress PDF")
                status = status_box("Before/after sizes will appear here.")
                out = gr.File(label="📥 Download", interactive=False, height=120)

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
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("4 · Apply"):
                btn = primary_button("✂️ Create PDF")
                status = status_box("Split results download as a ZIP.")
                out = gr.File(label="📥 Download", interactive=False, height=120)

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
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("3 · Convert"):
                btn = primary_button("🖼️ Convert to Images")
                status = status_box("Every page becomes one image.")
                out = gr.File(label="📥 Download", interactive=False, height=120)
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
        with gr.Column(scale=5, elem_classes="sticky-col"):
            with card("3 · Apply"):
                btn = primary_button("🔐 Apply")
                status = status_box("Removing a password needs the current password.")
                out = gr.File(label="📥 Download", interactive=False, height=120)

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
    theme = gr.themes.Soft(
        primary_hue="indigo", secondary_hue="violet", neutral_hue="slate", radius_size="lg",
        font=["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Inter", "Roboto", "Helvetica Neue", "sans-serif"],
    ).set(
        body_background_fill="#f4f5fb", body_background_fill_dark="#0b0f1a",
        background_fill_primary="#ffffff", background_fill_primary_dark="#131a2a",
        background_fill_secondary="#f6f7fb", background_fill_secondary_dark="#0f1522",
        border_color_primary="#e3e6f0", border_color_primary_dark="#232c40",
        block_background_fill="transparent", block_background_fill_dark="transparent",
        block_border_width="0px", block_shadow="none", block_padding="0px",
        block_label_background_fill="transparent", block_label_background_fill_dark="transparent",
        block_label_text_color="*neutral_600", block_label_text_color_dark="*neutral_300",
        block_label_border_width="0px", block_label_text_weight="600", block_label_padding="2px 4px",
        block_title_background_fill="transparent", block_title_background_fill_dark="transparent",
        block_title_text_color="*neutral_700", block_title_text_color_dark="*neutral_200",
        block_title_text_weight="600", block_title_padding="0px", block_title_border_width="0px",
        block_info_text_color="*neutral_500", block_info_text_color_dark="*neutral_400",
        input_background_fill="#ffffff", input_background_fill_dark="#0f1522",
        input_border_color="#d9dceb", input_border_color_dark="#2a3550", input_border_width="1px",
        input_shadow="none", input_shadow_focus="0 0 0 3px rgba(99,102,241,.18)",
        checkbox_label_background_fill="#ffffff", checkbox_label_background_fill_dark="#0f1522",
        checkbox_label_border_width="1px", checkbox_label_border_color="#d9dceb",
        checkbox_label_border_color_dark="#2a3550",
        checkbox_label_background_fill_selected="*primary_50",
        checkbox_label_background_fill_selected_dark="rgba(99,102,241,.22)",
        checkbox_label_text_color_selected="*primary_700", checkbox_label_text_color_selected_dark="#c7d2fe",
        checkbox_label_border_color_selected="*primary_400",
        button_secondary_background_fill="#ffffff", button_secondary_background_fill_dark="#1a2236",
        button_secondary_border_color="#d9dceb", button_secondary_border_color_dark="#2a3550",
        layout_gap="14px",
    )
    devices = detect_devices()
    backend = "pyvips" if USE_PYVIPS else "Pillow"
    gpu = [d for d in devices if d != CPU_DEVICE and "CPU" not in d]
    badges = [f"⚙️ {backend}", f"🧵 {MAX_WORKERS} workers"] + [f"🚀 {d}" for d in gpu] + ["🔒 100% offline"]

    with gr.Blocks(title=APP_NAME, analytics_enabled=False) as app:
        gr.HTML(f"""
            <div id="app-header">
              <div class="brand">
                <div class="logo">🖼️</div>
                <div><h1>{APP_NAME}</h1>
                <p>Resize photos, print passport sheets and work with PDFs — all on your computer.</p></div>
              </div>
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
