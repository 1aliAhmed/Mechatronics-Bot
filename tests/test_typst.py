from __future__ import annotations

from app.render.typst import escape_text, latex_math_to_typst, markdown_to_typst


def test_headings_and_rules():
    assert markdown_to_typst("# عنوان") == "= عنوان"
    assert markdown_to_typst("### بند") == "=== بند"
    assert markdown_to_typst("---") == "#line(length: 100%)"


def test_bold_and_lists():
    assert markdown_to_typst("**مهم**") == "*مهم*"
    assert markdown_to_typst("- عنصر") == "- عنصر"
    assert markdown_to_typst("1. أول") == "+ أول"
    assert markdown_to_typst("* نقطة") == "- نقطة"
    assert markdown_to_typst("*مهم*") == "_مهم_"


def test_escaping_of_typst_markup():
    assert markdown_to_typst("100# مهم") == "100\\# مهم"
    assert markdown_to_typst("راسل @user") == "راسل \\@user"
    assert markdown_to_typst("a < b") == "a \\< b"


def test_latex_math_conversion():
    assert markdown_to_typst("$\\frac{a}{b}$") == "$frac(a, b)$"
    assert markdown_to_typst("$\\dfrac{a}{b}$") == "$frac(a, b)$"
    assert markdown_to_typst("$\\tfrac{a}{b}$") == "$frac(a, b)$"
    assert markdown_to_typst("$\\sqrt{x^2+y^2}$") == "$sqrt(x^2+y^2)$"
    assert markdown_to_typst("$\\theta = 30^\\circ$") == "$theta = 30^degree$"
    assert markdown_to_typst("$F \\propto N$") == "$F ∝ N$"
    assert markdown_to_typst("$$\\int_0^1 f(x) dx$$") == "$ integral_0^1 f(x) dx $"
    assert latex_math_to_typst("\\alpha+\\beta") == "alpha+beta"
    assert latex_math_to_typst("985\\sin4.5") == "985 sin 4.5"
    assert latex_math_to_typst("\\sinh x") == "sinh x"
    assert latex_math_to_typst("W\\sin\\phi") == "W sin phi"
    assert latex_math_to_typst("W\\phi") == "W phi"
    assert latex_math_to_typst("\\displaystyle \\mu") == "mu"
    assert latex_math_to_typst("\\mathbb{R}") == "bb(R)"
    assert latex_math_to_typst("\\unknowncmd{x}") == "unknowncmd{x}"


def test_table_block_conversion():
    table = "| البند | القيمة |\n|---|---|\n| جهد | 5V |"
    out = markdown_to_typst(table)
    assert "#table(" in out
    assert "columns: 2" in out
    assert "[*البند*]" in out
    assert "[جهد]" in out
    assert "|" not in out


def test_code_fences_and_inline_code_are_untouched():
    fenced = "```python\n# comment\nprint(1)\n```"
    assert markdown_to_typst(fenced) == fenced
    assert markdown_to_typst("استخدم `x#y` هنا") == "استخدم `x#y` هنا"


def test_links_become_typst_links():
    assert markdown_to_typst("[الموقع](https://x.com)") == '#link("https://x.com")[الموقع]'


def test_escape_text_for_titles():
    assert escape_text("مقدمة #1 @name") == "مقدمة \\#1 \\@name"


def test_bare_latex_lines_become_math():
    assert markdown_to_typst("F = \\mu N") == "$ F = mu N $"
    assert markdown_to_typst("\\mu = \\frac{F}{N}") == "$ mu = frac(F, N) $"
    assert markdown_to_typst("C:\\Users\\user") == "C:\\Users\\user"
    assert markdown_to_typst("- عنصر \\mu") == "- عنصر \\mu"


def test_marker_only_lines_are_dropped():
    assert markdown_to_typst("**\nنص\n**") == "\nنص\n"
    assert markdown_to_typst("##") == ""
    assert markdown_to_typst("`") == ""


def test_unbalanced_backticks_are_escaped():
    assert markdown_to_typst("نص ` غير مغلق") == "نص \\` غير مغلق"
    assert markdown_to_typst("`x` عادي") == "`x` عادي"


def test_leftover_double_stars_are_removed():
    assert markdown_to_typst("**  نص مفتوح") == "  نص مفتوح"
    assert markdown_to_typst("**مغلق**") == "*مغلق*"
