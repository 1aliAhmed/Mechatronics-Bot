from __future__ import annotations

import asyncio
from pathlib import Path

from app.flows.clean import source_instructions
from app.render.typst import markdown_to_typst
from app.source_images import embed_images, extract_queries, fetch_commons_image, strip_markers


def test_marker_extraction_and_strip():
    md = "نص\n[صورة: friction force diagram]\n[صورة: pulley system]\nنهاية"
    assert extract_queries(md) == ["friction force diagram", "pulley system"]
    cleaned = strip_markers(md)
    assert "[صورة:" not in cleaned and "نص" in cleaned


def test_embed_images_uses_only_available():
    md = "[صورة: one]\n[صورة: two]"
    result = embed_images(md, [{"filename": "web-01.jpg", "caption": "شرح", "source": "https://commons.wikimedia.org/x", "license": "CC BY-SA 4.0"}])
    assert "![شرح](web-01.jpg)" in result
    assert "المصدر: [Wikimedia Commons]" in result
    assert "[صورة:" not in result


def test_simplify_and_faithful_instructions():
    simplified = source_instructions("بسّط الشرح.", mode="simplify")
    assert "التبسيط" in simplified
    assert "[صورة:" in simplified
    assert "لها الأولوية" in simplified
    faithful = source_instructions("ملاحظة المشرف", mode="faithful")
    assert "لا تحذف المحتوى" in faithful
    assert "لها الأولوية" in faithful


def test_typst_converts_safe_image_lines_only():
    typst = markdown_to_typst("![شرح](web-01.jpg)")
    assert '#figure(image("web-01.jpg", width: 72%)' in typst
    unsafe = markdown_to_typst("![x](../evil.png)")
    assert 'image("' not in unsafe


def test_fetch_commons_image_downloads_thumb(tmp_path):
    class Response:
        def __init__(self, payload=None, content=b""):
            self._payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        def __init__(self):
            self.urls = []

        async def get(self, url, **kwargs):
            self.urls.append(url)
            if "api.php" in url:
                return Response({
                    "query": {
                        "pages": {
                            "1": {
                                "imageinfo": [{
                                    "thumburl": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/diagram.jpg/1000px-diagram.jpg",
                                    "url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/diagram.jpg",
                                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Diagram.jpg",
                                    "extmetadata": {
                                        "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                        "Artist": {"value": "<a href='#'>Someone</a>"},
                                    },
                                }],
                            },
                        },
                    },
                })
            return Response(content=b"\xff\xd8fakejpeg")

        async def aclose(self):
            return None

    client = Client()
    found = asyncio.run(fetch_commons_image("friction diagram", tmp_path, 1, client))
    assert found is not None
    assert found["filename"] == "web-01.jpg"
    assert (tmp_path / "web-01.jpg").read_bytes().startswith(b"\xff\xd8")
    assert "CC BY-SA 4.0" in found["license"]
    assert found["caption"].startswith("friction diagram")


def test_fetch_commons_image_rejects_foreign_host(tmp_path):
    class Response:
        def __init__(self, payload=None, content=b""):
            self._payload = payload or {}
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class Client:
        async def get(self, url, **kwargs):
            return Response({"query": {"pages": {"1": {"imageinfo": [{"thumburl": "https://evil.example.com/x.jpg"}]}}}})

        async def aclose(self):
            return None

    assert asyncio.run(fetch_commons_image("anything", Path(tmp_path), 1, Client())) is None
