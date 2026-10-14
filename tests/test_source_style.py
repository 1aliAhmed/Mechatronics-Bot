from __future__ import annotations

from app.flows.clean import revision_instructions, source_instructions
from app.render.typst import markdown_to_typst


def test_source_instructions_include_style_spec():
    text = source_instructions("اكتب باختصار")
    assert "قواعد توحيد تنسيق المستندات" in text
    assert "تعليمات المشرف (لها الأولوية عند التعارض مع قواعد التغطية): اكتب باختصار" in text


def test_source_instructions_without_directive():
    text = source_instructions()
    assert "قواعد توحيد تنسيق المستندات" in text
    assert "تعليمات المشرف" not in text


def test_revision_instructions_include_style_spec():
    assert "قواعد توحيد تنسيق المستندات" in revision_instructions()


def test_wrapper_fence_is_removed():
    wrapped = "```markdown\n# عنوان\n\n## 1) قسم\n```"
    assert markdown_to_typst(wrapped) == "= عنوان\n\n== 1) قسم"
    fenced_code = "```python\nprint(1)\n```"
    assert markdown_to_typst(fenced_code) == fenced_code
