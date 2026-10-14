from __future__ import annotations

from io import BytesIO

from PIL import Image

from app.config import get_settings
from app.flows.clean import save_page_preview
from app.render.pdf import figures_appendix


def test_save_page_preview_creates_compact_jpeg(tmp_path):
    buffer = BytesIO()
    Image.new("RGB", (2000, 1500), "white").save(buffer, format="PNG")
    path = save_page_preview(buffer.getvalue(), tmp_path / "pages", 3)
    assert path.exists() and path.suffix == ".jpg"
    with Image.open(path) as preview:
        assert preview.width <= 1400


def test_figures_appendix_copies_and_references(tmp_path):
    image = tmp_path / "page-001.jpg"
    Image.new("RGB", (40, 30), "white").save(image)
    work = tmp_path / "work"
    work.mkdir()
    snippet = figures_appendix([image], work)
    assert "ملحق صور الصفحات" in snippet
    assert (work / "img-001.jpg").exists()
    assert '#figure(image("img-001.jpg"' in snippet
    assert "الصفحة 1" in snippet


def test_source_image_limit_default_is_30():
    import os
    os.environ.pop("SOURCE_IMAGE_LIMIT", None)
    assert get_settings().source_image_limit == 30
