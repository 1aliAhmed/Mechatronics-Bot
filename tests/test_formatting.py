from __future__ import annotations

from app.formatting import apply_style, clean_markup, strip_emoji


def test_strip_emoji_removes_symbols():
    assert strip_emoji("سؤال تقني مقبول ✅ — تابع 🛠️") == "سؤال تقني مقبول  — تابع "


def test_clean_markup_removes_headers_bold_and_fences():
    raw = "## 1. العنوان\n**نقطة**\n```python\nprint(1)\n```\nنص `code` عادي"
    clean = clean_markup(raw)
    assert "#" not in clean
    assert "**" not in clean
    assert "```" not in clean
    assert "print(1)" in clean
    assert "code" in clean


def test_clean_markup_converts_links_and_latex():
    assert clean_markup("راجع [الموقع](https://x.com) الآن") == "راجع الموقع (https://x.com) الآن"
    assert clean_markup("المعادلة $x^2$ هنا") == "المعادلة x^2 هنا"


def test_apply_style_is_idempotent_and_tidy():
    raw = "## عنوان\n\n\n\nسؤال ✅ **مهم**\n\nجواب"
    once = apply_style(raw)
    assert apply_style(once) == once
    assert "✅" not in once
    assert "#" not in once
    assert "**" not in once
    assert "\n\n\n" not in once
    assert once.startswith("عنوان")
