import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def make_image(tmp_path):
    """Create a noisy (photo-like, hard to compress) test image and return its path."""
    def _make(name, size=(800, 600), mode="RGB"):
        img = Image.effect_noise(size, 60).convert(mode)
        path = tmp_path / name
        img.save(path)
        return path
    return _make


@pytest.fixture
def make_pdf(tmp_path):
    """Create an n-page PDF made of large photo-like images."""
    def _make(name="doc.pdf", pages=1, size=(2000, 2800)):
        imgs = [Image.effect_noise(size, 60).convert("RGB") for _ in range(pages)]
        path = tmp_path / name
        imgs[0].save(path, "PDF", resolution=300, quality=95, save_all=True, append_images=imgs[1:])
        return path
    return _make
