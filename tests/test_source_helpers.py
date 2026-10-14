from __future__ import annotations

import asyncio

import fitz

from app.db import Database
from app.flows.clean import (caption_preset, count_pages, doc_keyboard, document_filename,
                             fast_page_text, iter_pages, page_origin, page_text_layer,
                             redo_source_paths, resolve_doc_digest, run_bounded)


def make_pdf(tmp_path, pages: int = 3):
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"page {index + 1}")
    path = tmp_path / "book.pdf"
    doc.save(path)
    doc.close()
    return path


def test_count_pages_and_truncation(tmp_path):
    path = make_pdf(tmp_path, 5)
    total, truncated = count_pages([str(path)], None)
    assert total == 5 and truncated is None
    total, truncated = count_pages([str(path)], 2)
    assert total == 2 and truncated == (2, 5)


def test_iter_pages_yields_one_png_per_page(tmp_path):
    path = make_pdf(tmp_path, 3)
    images = list(iter_pages([str(path)], None))
    assert len(images) == 3
    assert all(image.startswith(b"\x89PNG") for image in images)
    assert len(list(iter_pages([str(path)], 1))) == 1


def test_caption_preset_detection():
    assert caption_preset("/flash اشرح هذه الصور")
    assert caption_preset("/summary")
    assert not caption_preset("read the first 5 pages")
    assert not caption_preset("")


def test_resolve_doc_digest_validates_token(tmp_path):
    db = Database(tmp_path / "docs.db")
    full = "a" * 64
    db.execute("INSERT INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (full, "/tmp/x.pdf", "body", "[]"))
    assert resolve_doc_digest(db, full[:32]) == full
    assert resolve_doc_digest(db, full) == full
    assert resolve_doc_digest(db, "%") is None
    assert resolve_doc_digest(db, "zzz") is None


def test_redo_source_paths_handles_revisions(tmp_path):
    db = Database(tmp_path / "docs.db")
    parent, child, empty = "b" * 64, "c" * 64, "d" * 64
    db.execute("INSERT INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (parent, "/tmp/p.pdf", "orig", '["/tmp/source.pdf"]'))
    db.execute("INSERT INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (child, "/tmp/c.pdf", "rev", parent))
    db.execute("INSERT INTO docs(hash,artifact,markdown,source) VALUES(?,?,?,?)", (empty, "/tmp/d.pdf", "x", ""))
    assert redo_source_paths(db, parent) == (parent, ["/tmp/source.pdf"])
    assert redo_source_paths(db, child) == (parent, ["/tmp/source.pdf"])
    assert redo_source_paths(db, empty) == (empty, [])


def test_doc_keyboard_has_single_action_row():
    keyboard = doc_keyboard("a" * 64)
    assert len(keyboard.inline_keyboard) == 1
    datas = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert f"doc:publish:{'a' * 32}" in datas
    assert not any(data.startswith("docpub") for data in datas)


def test_document_filename_from_title():
    assert document_filename("# تجربة الاحتكاك\n\n## 1) قسم", ".pdf") == "تجربة الاحتكاك.pdf"
    assert document_filename("", ".pdf") == "مادة دراسية.pdf"
    assert document_filename("# A/B: C? D\n", ".md") == "A B C D.md"


def test_page_text_layer_reads_digital_text(tmp_path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello digital text layer " * 10)
    path = tmp_path / "text.pdf"
    doc.save(path)
    assert "Hello digital text layer" in page_text_layer(str(path), 1)
    blank = fitz.open()
    blank.new_page()
    blank_path = tmp_path / "blank.pdf"
    blank.save(blank_path)
    assert page_text_layer(str(blank_path), 1) is None


def _solid_pixmap(size: int) -> fitz.Pixmap:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, size, size))
    pixmap.set_rect(pixmap.irect, (200, 100, 50))
    return pixmap


def _fill_lines(page, text: str, lines: int = 6) -> None:
    for index in range(lines):
        page.insert_text((72, 72 + 16 * index), text)


def test_fast_page_text_routes_only_image_free_pages(tmp_path):
    doc = fitz.open()
    text_page = doc.new_page()
    _fill_lines(text_page, "Native digital text without any images")
    figure_page = doc.new_page()
    _fill_lines(figure_page, "Text plus a real figure")
    figure_page.insert_image(fitz.Rect(72, 220, 172, 320), stream=_solid_pixmap(120).tobytes("png"))
    logo_page = doc.new_page()
    _fill_lines(logo_page, "Text with a tiny logo only")
    logo_page.insert_image(fitz.Rect(72, 220, 92, 240), stream=_solid_pixmap(40).tobytes("png"))
    path = tmp_path / "routing.pdf"
    doc.save(path)
    assert "Native digital text" in fast_page_text(str(path), 1)
    assert fast_page_text(str(path), 2) is None       # real figure -> vision
    assert "tiny logo" in fast_page_text(str(path), 3)  # logo-sized images are ignored


def test_page_origin_maps_multi_file_sources(tmp_path):
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    pdf = tmp_path / "book.pdf"
    doc.save(pdf)
    image = tmp_path / "scan.jpg"
    image.write_bytes(b"x")
    sources = [str(pdf), str(image)]
    assert page_origin(sources, None, 1) == (str(pdf), 1)
    assert page_origin(sources, None, 3) == (str(pdf), 3)
    assert page_origin(sources, None, 4) == (str(image), 1)
    assert page_origin(sources, None, 5) is None
    assert page_origin(sources, 2, 3) == (str(image), 1)


def test_run_bounded_limits_concurrency_and_covers_all_items():
    active = 0
    peak = 0
    seen = []

    async def worker(item):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        seen.append(item)
        active -= 1

    asyncio.run(run_bounded(iter(range(10)), worker, limit=3))
    assert sorted(seen) == list(range(10))
    assert peak <= 3
