import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader

from pixpress import pdf_tools as t


def test_parse_ranges():
    assert t.parse_ranges("1-3, 5, 8-end", 10) == [[0, 1, 2], [4], [7, 8, 9]]
    assert t.parse_ranges("3-1", 5) == [[2, 1, 0]]
    assert t.parse_ranges("", 5) == []
    with pytest.raises(ValueError):
        t.parse_ranges("12", 5)
    with pytest.raises(ValueError):
        t.parse_ranges("abc", 5)


def test_order_paths(make_image):
    a, b, c = (str(make_image(n)) for n in ("b10.jpg", "b2.jpg", "a.png"))
    assert [p.name for p in t.order_paths([a, b, c], "Name A → Z")] == ["a.png", "b2.jpg", "b10.jpg"]
    assert [p.name for p in t.order_paths([a, b, c], custom="3,1")] == ["a.png", "b10.jpg", "b2.jpg"]


@pytest.mark.parametrize("page_size", list(t.PDF_PAGE_SIZES))
def test_merge_images_and_pdfs(make_image, make_pdf, page_size):
    files = [make_image("a.jpg", (1600, 1000)), make_pdf(pages=2), make_image("b.png", mode="RGBA")]
    out, status = t.merge_to_pdf([str(f) for f in files], "As uploaded", "", page_size, 10,
                                 "None – keep original quality", 0)
    assert out, status
    reader = PdfReader(out)
    assert len(reader.pages) == 4
    first = reader.pages[0].mediabox
    assert first.width > first.height  # landscape image → landscape page


def test_compression_levels_shrink(make_pdf):
    src = make_pdf()
    out, _ = t.compress_pdfs([str(src)], "Balanced – recommended", 0)
    assert Path(out).stat().st_size < src.stat().st_size / 2


def test_target_size(make_pdf):
    src = make_pdf(pages=2)
    out, status = t.compress_pdfs([str(src)], "Target size (MB)", 0.5)
    assert Path(out).stat().st_size <= 0.5 * 1024 * 1024, status
    assert len(PdfReader(out).pages) == 2


def test_organize(make_pdf):
    src = str(make_pdf(pages=5, size=(200, 280)))
    out, _ = t.organize_pdf(src, t.ORGANIZE_MODES[0], "5, 1-2", "1", "90°")
    pages = PdfReader(out).pages
    # rotation uses original page numbers: original page 1 is now output page 2
    assert len(pages) == 3 and pages[0].rotation == 0 and pages[1].rotation == 90

    out, _ = t.organize_pdf(src, t.ORGANIZE_MODES[1], "2-4", "", "0°")
    assert len(PdfReader(out).pages) == 2

    out, _ = t.organize_pdf(src, t.ORGANIZE_MODES[3], "", "", "0°")
    assert len(zipfile.ZipFile(out).namelist()) == 5


def test_pdf_to_images(make_pdf):
    out, previews, _ = t.pdf_to_images([str(make_pdf(pages=3, size=(200, 280)))], "PNG", 72)
    assert len(zipfile.ZipFile(out).namelist()) == 3 and len(previews) == 3


def test_password_roundtrip(make_pdf):
    src = str(make_pdf(pages=2, size=(200, 280)))
    locked, _ = t.protect_pdf(src, "Add password", "s3cret", "s3cret")
    assert PdfReader(locked).is_encrypted
    assert t.protect_pdf(locked, "Remove password", "wrong")[0] is None
    unlocked, _ = t.protect_pdf(locked, "Remove password", "s3cret")
    reader = PdfReader(unlocked)
    assert not reader.is_encrypted and len(reader.pages) == 2
