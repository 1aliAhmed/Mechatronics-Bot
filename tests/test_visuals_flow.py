from __future__ import annotations

import asyncio

from app.flows.admin import wants_visual
from app.flows.visuals import compose_visual, render_blocks, strip_fences


def test_strip_fences_removes_code_blocks():
    assert strip_fences("```python\nimport matplotlib\n```") == "import matplotlib"
    assert strip_fences("import matplotlib") == "import matplotlib"
    assert strip_fences("") == ""


def test_wants_visual_detection():
    assert wants_visual("make a graph")
    assert wants_visual("i want an image")
    assert wants_visual("draw me a sine wave")
    assert wants_visual("ارسم لي دائرة")
    assert wants_visual("سويلي رسم بياني")
    assert wants_visual("رسم mechtronics logo")
    assert wants_visual("رسم دائرة نصف قطرها 5")
    assert wants_visual("أريد رسم منحنى الجهد")
    assert wants_visual("صمم شعار المادة")
    assert wants_visual("مخطط دائرة كهربائية")
    assert not wants_visual("explain graph theory basics")
    assert not wants_visual("what is image processing")
    assert not wants_visual("اشرح الرسم البياني المرفق")
    assert not wants_visual("ما هو المخطط الكهربائي؟")

class _Provider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, model, messages, **params):
        self.calls += 1
        return self.replies.pop(0)


def test_compose_visual_repairs_broken_code():
    broken = "def broken(:\n    pass"
    good = "import matplotlib.pyplot as plt\nplt.plot([1, 2, 3], [1, 4, 9])\nplt.title('demo')"
    provider = _Provider([(broken, {"n": 1}), (good, {"n": 2})])
    image, response, code = asyncio.run(compose_visual(provider, "model", "draw a curve"))
    assert image.exists()
    assert provider.calls == 2
    assert "plt.plot" in code


def test_compose_visual_strips_fences_before_render():
    fenced = "```python\nimport matplotlib.pyplot as plt\nplt.plot([0, 1], [0, 1])\n```"
    provider = _Provider([(fenced, {})])
    image, response, code = asyncio.run(compose_visual(provider, "model", "draw a line"))
    assert image.exists()
    assert provider.calls == 1


def test_render_blocks_renders_python_and_cleans_text():
    answer = "هذا مثال:\n```python\nimport matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])\n```\nوبعد الكود."
    images, text = asyncio.run(render_blocks(answer))
    assert len(images) == 1 and images[0].exists()
    assert "plt.plot" not in text
    assert "هذا مثال" in text and "وبعد الكود" in text


def test_render_blocks_skips_non_renderable_code():
    answer = "```python\nprint(1)\n```"
    images, text = asyncio.run(render_blocks(answer))
    assert images == [] and text == answer
