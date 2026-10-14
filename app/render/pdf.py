from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from app.render.typst import escape_text, markdown_to_typst

log = logging.getLogger(__name__)

TEMPLATE = '''#set page(paper: "a4", margin: (x: 1.8cm, y: 2cm), numbering: "1", number-align: center)
#set text(font: ("Noto Naskh Arabic", "Noto Sans Arabic", "Droid Arabic Kufi", "Noto Color Emoji", "Noto Emoji", "DejaVu Sans"), size: 10pt, lang: "ar", dir: rtl)
#set par(justify: true)
#show math.equation: set text(font: "New Computer Modern Math")
#show raw: set text(font: "DejaVu Sans Mono", size: 9pt)
'''


def typst_binary() -> str:
    return os.environ.get("TYPST_BIN") or shutil.which("typst") or "/usr/local/bin/typst"


def _cover(title: str) -> str:
    return (
        "#align(center + horizon)[\n"
        f'  #text(size: 24pt, weight: "bold")[{escape_text(title)}]\n\n'
        "  #v(1em)\n"
        "  #line(length: 45%, stroke: 1pt)\n"
        "  #v(1em)\n"
        "  #text(size: 12pt)[مادة دراسية معدّة للمراجعة]\n"
        "  #v(0.5em)\n"
        '  #text(size: 10pt)[#datetime.today().display("[year]-[month]-[day]")]\n'
        "]\n"
        "#pagebreak()\n"
    )


def figures_appendix(figures: list[Path], workdir: Path) -> str:
    """Copy page previews next to the document and build the Typst appendix snippet."""
    lines = ["#pagebreak()", "= ملحق صور الصفحات"]
    for index, path in enumerate(figures, 1):
        target = f"img-{index:03d}{path.suffix.lower()}"
        shutil.copyfile(path, workdir / target)
        lines.append(f'#figure(image("{target}", width: 100%), caption: [الصفحة {index}])')
    return "\n".join(lines)


def render_pdf(markdown: str, output: Path, workdir: Path, *, title: str | None = None, figures: list[Path] | None = None) -> bool:
    workdir = Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    source = workdir / "document.typ"
    output = Path(output).resolve()
    body = markdown_to_typst(markdown)
    document = TEMPLATE + "\n" + (_cover(title) + "\n" if title else "") + body
    if figures:
        document += "\n" + figures_appendix(figures, workdir)
    source.write_text(document, encoding="utf-8")
    try:
        result = subprocess.run([typst_binary(), "compile", str(source), str(output)], cwd=workdir, capture_output=True, text=True, timeout=90, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("Typst invocation failed: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("Typst render failed (rc=%s): %s", result.returncode, (result.stderr or "")[-400:])
    return result.returncode == 0 and output.exists()
