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
