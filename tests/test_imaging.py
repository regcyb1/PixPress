import zipfile

from PIL import Image

from pixpress.imaging import process_images


def _resize(files, **kw):
    args = dict(resolution_preset="512 × 512", custom_width=0, custom_height=0, maintain_aspect=True,
                ppi_preset="300", custom_ppi=0, quality=90)
    args.update(kw)
    return process_images([str(f) for f in files], **args)


def test_same_stem_files_are_not_overwritten(make_image):
    files = [make_image("photo.jpg"), make_image("photo.png"), make_image("other.webp")]
    out, status = _resize(files)
    names = zipfile.ZipFile(out).namelist()
    assert len(names) == 3
    assert "photo.jpg" in names and "photo (2).jpg" in names


def test_single_file_keeps_aspect_and_dpi(make_image):
    out, _ = _resize([make_image("a.png", (1000, 500))])
    img = Image.open(out)
    assert img.format == "JPEG"
    assert img.size == (512, 256)
    assert round(img.info["dpi"][0]) == 300


def test_png_output_keeps_transparency(make_image):
    out, _ = _resize([make_image("t.png", mode="RGBA")], output_format="PNG")
    assert Image.open(out).mode == "RGBA"


def test_max_file_size_is_respected(make_image):
    out, status = _resize([make_image("big.png", (3000, 2000))], resolution_preset="2048 × 2048", max_kb=150)
    assert out.endswith(".jpg")
    from pathlib import Path
    assert Path(out).stat().st_size <= 150 * 1024, status


def test_empty_custom_size_is_rejected_not_crashing(make_image):
    out, status = _resize([make_image("a.jpg")], resolution_preset="Custom", custom_width=None, custom_height=None)
    assert out is None and "positive" in status


def test_jpeg_dpi_patch_writes_correct_offsets(tmp_path):
    from pixpress.imaging import _patch_jpeg_dpi
    p = tmp_path / "x.jpg"
    Image.new("RGB", (10, 10)).save(p, dpi=(72, 72))
    _patch_jpeg_dpi(str(p), 600)
    img = Image.open(p)
    assert round(img.info["dpi"][0]) == 600
    assert img.info["jfif_version"] == (1, 1)
