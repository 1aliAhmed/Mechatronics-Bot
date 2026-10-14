from __future__ import annotations

import re

_GREEK = {
    "alpha": "alpha", "beta": "beta", "gamma": "gamma", "delta": "delta",
    "epsilon": "epsilon", "zeta": "zeta", "eta": "eta", "theta": "theta",
    "kappa": "kappa", "lambda": "lambda", "mu": "mu", "nu": "nu", "xi": "xi",
    "rho": "rho", "sigma": "sigma", "tau": "tau", "phi": "phi", "chi": "chi",
    "psi": "psi", "omega": "omega", "Gamma": "Gamma", "Delta": "Delta",
    "Theta": "Theta", "Lambda": "Lambda", "Sigma": "Sigma", "Phi": "Phi",
    "Psi": "Psi", "Omega": "Omega",
}

_MATH_SIMPLE = {
    "\\times": "times", "\\cdot": "dot", "\\div": "div",
    "\\pm": "plus.minus", "\\mp": "minus.plus",
    "\\leq": "<=", "\\le": "<=", "\\geq": ">=", "\\ge": ">=",
    "\\neq": "!=", "\\ne": "!=", "\\approx": "approx", "\\equiv": "equiv",
    "\\propto": "∝", "\\sim": "~", "\\simeq": "approx",
    "\\infty": "infinity", "\\sum": "sum", "\\prod": "product",
    "\\int": "integral", "\\partial": "diff", "\\nabla": "nabla",
    "\\to": "arrow.r", "\\rightarrow": "arrow.r", "\\leftarrow": "arrow.l",
    "\\Rightarrow": "arrow.r.double", "\\left": "", "\\right": "",
    "\\uparrow": "arrow.t", "\\downarrow": "arrow.b",
    "\\ldots": "dots.h", "\\cdots": "dots.c",
    "\\angle": "angle", "\\perp": "perp", "\\parallel": "parallel",
    "\\(\\(": "(", "\\)\\)": ")", "\\(": "(", "\\)": ")", "\\[": "(", "\\]": ")",
    "\\!": "", "\\,": " ", "\\;": " ", "\\:": " ", "\\quad": " ", "\\qquad": " ",
    "\\sinh": "sinh ", "\\cosh": "cosh ", "\\tanh": "tanh ",
    "\\sin": "sin ", "\\cos": "cos ", "\\tan": "tan ", "\\cot": "cot ",
    "\\sec": "sec ", "\\csc": "csc ",
    "\\log": "log ", "\\ln": "ln ", "\\exp": "exp ", "\\lim": "lim ", "\\det": "det ",
    "\\max": "max ", "\\min": "min ",
    "\\bigg": "", "\\Bigg": "", "\\bigl": "", "\\bigr": "", "\\Bigl": "", "\\Bigr": "",
    "\\big": "", "\\Big": "",
    "\\displaystyle": "", "\\textstyle": "", "\\scriptstyle": "", "\\scriptscriptstyle": "",
    "\\limits": "", "\\nolimits": "", "\\nonumber": "", "\\notag": "",
    "\\circ": "degree", "\\degree": "degree", "\\%": "%", "\\&": "&", "\\#": "#",
}

_CODE_SPAN = re.compile(r"`[^`\n]*`")
_MATH_SPAN = re.compile(r"\$\$([^$]+)\$\$|\$([^$\n]+)\$")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_MARKER_ONLY = re.compile(r"^[ \t]*(?:[*#`~]+[ \t]*)+$")
_WRAPPER_FENCE = re.compile(r"^```(?:markdown|md)?[ \t]*$")
_IMAGE_LINE = re.compile(r"^\s*!\[(?P<caption>[^\]]*)\]\((?P<path>[^)\s]+)\)\s*$")
_SAFE_IMAGE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_BARE_MATH = re.compile(r"^[A-Za-z0-9\\{}\[\]()+\-*/=.,^_' ]+$")


def escape_text(text: str) -> str:
    for character in "#@$<>":
        text = text.replace(character, "\\" + character)
    return text


def latex_math_to_typst(body: str) -> str:
    text = body
    for _ in range(3):
        text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"frac(\1, \2)", text)
    text = re.sub(r"\\[dt]?sqrt\{([^{}]*)\}", r"sqrt(\1)", text)
    text = re.sub(r"\\text\{([^{}]*)\}", r'"\1"', text)
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r'"\1"', text)
    text = re.sub(r"\\operatorname\{([^{}]*)\}", r'"\1"', text)
    text = re.sub(r"\\mathbb\{([^{}]*)\}", r"bb(\1)", text)
    text = re.sub(r"\\mathcal\{([^{}]*)\}", r"cal(\1)", text)
    text = re.sub(r"\\mathbf\{([^{}]*)\}", r"bold(\1)", text)
    text = re.sub(r"\\boldsymbol\{([^{}]*)\}", r"bold(\1)", text)
    text = re.sub(r"\\[hv]space\{[^{}]*\}", " ", text)
    text = re.sub(r"\\vec\{([^{}]*)\}", r"arrow(\1)", text)
    text = re.sub(r"\\hat\{([^{}]*)\}", r"hat(\1)", text)
    text = re.sub(r"\\bar\{([^{}]*)\}", r"macron(\1)", text)
    text = re.sub(r"\\dot\{([^{}]*)\}", r"dot(\1)", text)
    text = re.sub(r"\\overline\{([^{}]*)\}", r"overline(\1)", text)
    greek = "|".join(sorted(_GREEK, key=len, reverse=True))
    text = re.sub(rf"(?<=[A-Za-z0-9])\\({greek})(?![A-Za-z])", lambda match: " " + _GREEK[match.group(1)], text)
    text = re.sub(rf"\\({greek})(?![A-Za-z])", lambda match: _GREEK[match.group(1)], text)
    for command, replacement in _MATH_SIMPLE.items():
        text = text.replace(command, replacement)
    text = re.sub(r"(?<=[A-Za-z0-9])(sinh|cosh|tanh|sin|cos|tan|cot|sec|csc|log|ln|exp|lim|det|max|min)(?![A-Za-z])", r" \1", text)
    text = re.sub(r"\\([A-Za-z]+)", r"\1", text)
    return re.sub(r" {2,}", " ", text).strip()


def _process_inline(text: str) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"\u0000{len(placeholders) - 1}\u0000"

    text = _CODE_SPAN.sub(lambda match: stash(match.group(0)), text)
    if text.count("`") % 2 == 1:
        text = text.replace("`", "\\`")

    def math(match: re.Match[str]) -> str:
        if match.group(1) is not None:
            return stash("$ " + latex_math_to_typst(match.group(1)) + " $")
        return stash("$" + latex_math_to_typst(match.group(2)) + "$")

    text = _MATH_SPAN.sub(math, text)
    text = _LINK.sub(lambda match: stash(f'#link("{match.group(2)}")[{_process_inline(match.group(1))}]'), text)
    text = escape_text(text)
    text = re.sub(r"\*\*(.+?)\*\*", "\u0001\\1\u0002", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", "\u0001\\1\u0002", text, flags=re.DOTALL)
    text = re.sub(r"(?<!\*)\*([^*\n]+?)\*(?!\*)", r"_\1_", text)
    text = text.replace("\u0001", "*").replace("\u0002", "*")
    for index, value in enumerate(placeholders):
        text = text.replace(f"\u0000{index}\u0000", value)
    return text


def _table(rows: list[str]) -> list[str]:
    parsed: list[list[str]] = []
    for row in rows:
        parsed.append([cell.strip() for cell in row.strip().strip("|").split("|")])
    parsed = [row for row in parsed if not re.match(r"^[\s:\-]+$", "".join(row))]
    width = max(len(row) for row in parsed)
    lines = ["#table(", f"  columns: {width},", "  stroke: 0.5pt,", "  inset: 6pt,"]
    for index, row in enumerate(parsed):
        for cell in row + [""] * (width - len(row)):
            text = _process_inline(cell)
            if index == 0 and text:
                text = f"*{text}*"
            lines.append(f"  [{text}],")
    lines.append(")")
    return lines


def markdown_to_typst(markdown: str) -> str:
    lines = markdown.replace("\r\n", "\n").split("\n")
    if len(lines) >= 2 and _WRAPPER_FENCE.match(lines[0].strip()) and lines[-1].strip() == "```":
        lines = lines[1:-1]
    out: list[str] = []
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            i += 1
            continue
        if in_code:
            out.append(line)
            i += 1
            continue
        if _MARKER_ONLY.match(line):
            out.append("")
            i += 1
            continue
        if line.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:\-|]+\|\s*$", lines[i + 1]):
            block = []
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                block.append(lines[j])
                j += 1
            out.extend(_table(block))
            i = j
            continue
        bare = line.strip()
        if (bare and "\\" in bare and len(bare) < 160 and not _ARABIC.search(bare)
                and _BARE_MATH.match(bare) and (bare[0] == "\\" or bare[0].isalpha())
                and ("=" in bare or bare[0] == "\\")):
            # Safety net for equations written as bare LaTeX without $ delimiters.
            out.append("$ " + latex_math_to_typst(bare) + " $")
            i += 1
            continue
        image = _IMAGE_LINE.match(line)
        if image:
            name = image.group("path")
            if _SAFE_IMAGE_NAME.match(name):
                caption = _process_inline(image.group("caption").strip())
                if caption:
                    out.append(f'#align(center)[#figure(image("{name}", width: 72%), caption: [{caption}])]')
                else:
                    out.append(f'#align(center)[#figure(image("{name}", width: 72%))]')
                i += 1
                continue
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            out.append("=" * len(heading.group(1)) + " " + _process_inline(heading.group(2).strip()))
            i += 1
            continue
        if re.match(r"^\s*(---+|\*\*\*+|___+)\s*$", line):
            out.append("#line(length: 100%)")
            i += 1
            continue
        numbered = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", line)
        if numbered:
            out.append(numbered.group(1) + "+ " + _process_inline(numbered.group(3)))
            i += 1
            continue
        bullet = re.match(r"^(\s*)[-*+]\s+(.*)$", line)
        if bullet:
            out.append(bullet.group(1) + "- " + _process_inline(bullet.group(2)))
            i += 1
            continue
        out.append(_process_inline(line))
        i += 1
    return "\n".join(out).replace("**", "")
