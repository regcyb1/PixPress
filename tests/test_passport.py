from pypdf import PdfReader

from pixpress.passport import PAGE_SIZES, PHOTO_SIZES, _assign_slots, _sheet_grid, make_passport_sheet


def test_a4_passport_grid():
    cols, rows, _, _ = _sheet_grid(210, 297, 35, 45, 5, 3)
    assert (cols, rows) == (5, 6)


def test_keep_together_moves_to_next_page():
    slots = _assign_slots(n_photos=2, copies=4, per_page=6, keep_together=True)
    assert [s for i, s in slots if i == 1] == [6, 7, 8, 9]


def test_sheet_pdf(make_image):
    files = [str(make_image(f"p{i}.jpg")) for i in range(3)]
    pdf, previews, status = make_passport_sheet(
        files, next(iter(PHOTO_SIZES)), 0, 0, next(iter(PAGE_SIZES)), "Portrait",
        copies=12, margin=5, gap=3, fit_mode="Crop", keep_together=True, cut_guides=True)
    assert len(PdfReader(pdf).pages) == 2
    assert len(previews) == 2


def test_pdf_input_becomes_photos(make_pdf, make_image):
    from pixpress.passport import expand_inputs
    pdf_path = make_pdf("student.pdf", pages=2, size=(600, 800))
    img = make_image("a.jpg")
    paths, errors = expand_inputs([str(pdf_path), str(img)])
    assert not errors
    assert len(paths) == 3


def test_sheet_from_pdf(make_pdf):
    pdf_path = make_pdf("student.pdf", pages=1, size=(600, 800))
    out, previews, status = make_passport_sheet(
        [str(pdf_path)], next(iter(PHOTO_SIZES)), 0, 0, next(iter(PAGE_SIZES)), "Portrait",
        copies=4, margin=5, gap=3, fit_mode="Crop", keep_together=True, cut_guides=False)
    assert out and len(PdfReader(out).pages) == 1


def test_trim_whitespace_finds_photo():
    from PIL import Image

    from pixpress.passport import trim_whitespace
    page = Image.new("RGB", (1000, 1400), "white")
    page.paste(Image.new("RGB", (200, 260), (40, 80, 120)), (400, 500))
    trimmed = trim_whitespace(page, pad_ratio=0)
    assert trimmed.size == (200, 260)


def test_crop_box_keeps_aspect_and_bounds():
    from pixpress.passport import crop_box
    aspect = 35 / 45
    for crop in (None, {"zoom": 2, "x": 100, "y": -100}, {"zoom": 3.5, "x": -40, "y": 70}):
        l, t, r, b = crop_box((1200, 800), aspect, crop)
        assert 0 <= l < r <= 1200 and 0 <= t < b <= 800
        assert abs((r - l) / (b - t) - aspect) < 0.01


def test_crop_applied_in_sheet(make_image):
    from pixpress.passport import apply_crop
    from PIL import Image
    p = make_image("c.jpg", size=(800, 600))
    rotated = apply_crop(Image.open(p), 1.0, {"rotate": 90})
    assert rotated.size == (600, 600)
    out, _, _ = make_passport_sheet(
        [str(p)], next(iter(PHOTO_SIZES)), 0, 0, next(iter(PAGE_SIZES)), "Portrait",
        copies=2, margin=5, gap=3, fit_mode="Crop", keep_together=True, cut_guides=True,
        crops={str(p): {"zoom": 2, "x": 50, "y": 0, "rotate": 90}})
    assert out
