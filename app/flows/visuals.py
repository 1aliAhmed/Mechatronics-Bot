from __future__ import annotations

import asyncio
import ast
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

ALLOWED_IMPORTS = {"matplotlib", "numpy", "math", "statistics", "graphviz"}

_FENCE_BLOCK = re.compile(r"```(\w*)[ \t]*\n(.*?)```", re.DOTALL)

VISUAL_INSTRUCTIONS = {
    "python": "Output only matplotlib Python code for a clear educational figure, no prose and no fenced block. Do not write files, use the network, or call system commands.",
    "dot": "Output only Graphviz DOT for a clear educational diagram, no prose and no fenced block.",
}

SAVEFIG = "\nimport matplotlib.pyplot as plt\nplt.savefig('visual.png', dpi=160, bbox_inches='tight')"


def strip_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


CHART_HINTS = ("منحنى", "بياني", "مخطط", "معادلة", "دالة", "محور", "محاور", "هندسي", "كهربائية", "كهربائي", "دارة", "مقاومة", "متجه", "توزيع", "إحصاء", "plot", "graph", "chart", "diagram", "circuit", "sine", "cosine", "histogram", "axis", "function", "equation", "curve", "waveform")
ILLUSTRATION_HINTS = ("شعار", "لوجو", "logo", "icon", "أيقونة", "صورة", "رسمة فنية", "رسم فني", "ملصق", "بوستر", "poster", "خلفية", "خلفيه", "wallpaper", "sticker", "illustration", "artwork", "photo of", "شخصية", "أنمي")


def visual_kind(text: str) -> str:
    """Route a drawing request: 'chart' for plots/diagrams, 'illustration' for pictures/logos."""
    lowered = (text or "").casefold()
    if any(hint in lowered for hint in CHART_HINTS):
        return "chart"
    if any(hint in lowered for hint in ILLUSTRATION_HINTS):
        return "illustration"
    return "chart"


async def compose_visual(provider, model: str, request: str, kind: str = "python", attempts: int = 3) -> tuple[Path, dict, str]:
    """Ask the model for render code, render it, and repair it on failure using the traceback."""
    instruction = VISUAL_INSTRUCTIONS.get(kind, VISUAL_INSTRUCTIONS["python"])
    generated, response = await provider.chat(model, [{"role": "system", "content": instruction}, {"role": "user", "content": request}], temperature=0.1)
    code = strip_fences(generated)
    for attempt in range(attempts):
        render_code = code + SAVEFIG if kind == "python" else code
        try:
            image = await asyncio.to_thread(render_visual, render_code, kind=kind)
            return image, response, code
        except Exception as exc:
            if attempt == attempts - 1:
                raise
            repair = f"The code failed with this error:\n{str(exc)[:1200]}\nFix it and output the full corrected code only."
            generated, response = await provider.chat(model, [{"role": "system", "content": instruction}, {"role": "user", "content": request}, {"role": "assistant", "content": code}, {"role": "user", "content": repair}], temperature=0.1)
            code = strip_fences(generated)
    raise RuntimeError("visual composition failed")


def _looks_renderable(lang: str, code: str) -> str | None:
    stripped = code.strip()
    lower = stripped.casefold()
    if lang in {"dot", "graphviz"} or lower.startswith(("digraph", "strict digraph", "graph ", "strict graph")):
        return "dot"
    if "plt." in stripped or "matplotlib" in lower or "savefig" in lower:
        return "python"
    return None


async def render_blocks(answer: str, limit: int = 2) -> tuple[list[Path], str]:
    """Render fenced matplotlib/DOT blocks found in an answer; return images and the answer without them."""
    images: list[Path] = []
    parts: list[str] = []
    last = 0
    for match in _FENCE_BLOCK.finditer(answer):
        if len(images) >= limit:
            break
        kind = _looks_renderable(match.group(1), match.group(2))
        if not kind:
            continue
        try:
            code = match.group(2)
            if kind == "python":
                code += SAVEFIG
            images.append(await asyncio.to_thread(render_visual, code, kind=kind))
            parts.append(answer[last:match.start()])
            last = match.end()
        except Exception as exc:
            log.warning("Inline render skipped: %s", str(exc)[:200])
    if not images:
        return [], answer
    parts.append(answer[last:])
    cleaned = "\n".join(part.strip("\n") for part in parts).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return images, cleaned


def _shape(source: str) -> str:
    """Shape quoted Arabic strings in common matplotlib label calls when extras exist."""
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
    except ImportError:
        return source
    pattern = re.compile(r"((?:title|xlabel|ylabel|text|annotate)\([^\n]*?)(['\"])([^'\"]*[\u0600-\u08ff][^'\"]*)\2")
    return pattern.sub(lambda m: m.group(1) + repr(get_display(arabic_reshaper.reshape(m.group(3)))), source)


def validate_python(source: str) -> None:
    if len(source) > 30000:
        raise ValueError("Renderer source is too large")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".")[0] for alias in node.names] if isinstance(node, ast.Import) else [(node.module or "").split(".")[0]]
            if any(name not in ALLOWED_IMPORTS for name in names):
                raise ValueError("Unsupported import")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "exec", "eval", "compile", "__import__", "breakpoint", "input"}:
            raise ValueError("Unsafe call")
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            raise ValueError("Unsafe attribute")
        if isinstance(node, ast.Name) and node.id in {"globals", "locals", "vars", "getattr", "setattr", "delattr"}:
            raise ValueError("Unsafe reflective access")


def render_visual(source: str, *, kind: str = "python", timeout: int = 30) -> Path:
    """Validated, isolated-interpreter execution with timeout; not an OS security sandbox."""
    directory = Path(tempfile.mkdtemp(prefix="megatronics-visual-"))
    output = directory / "visual.png"
    try:
        if kind == "python":
            validate_python(source)
            script = directory / "render.py"
            script.write_text("import matplotlib\nmatplotlib.use('Agg')\n" + _shape(source) + "\n", encoding="utf-8")
            env = {"PATH": os.environ.get("PATH", ""), "MPLCONFIGDIR": str(directory), "HOME": str(directory), "MPLBACKEND": "Agg"}
            proc = subprocess.run([sys.executable, "-I", str(script)], cwd=directory, env=env, capture_output=True, timeout=max(1, min(timeout, 60)), check=False)
        elif kind == "dot":
            if len(source) > 30000 or "\x00" in source:
                raise ValueError("Invalid DOT source")
            proc = subprocess.run(["dot", "-Tpng", "-o", str(output)], input=source.encode(), cwd=directory, capture_output=True, timeout=max(1, min(timeout, 60)), check=False)
        else:
            raise ValueError("kind must be python or dot")
        if proc.returncode or not output.exists() or output.stat().st_size > 20 * 1024 * 1024:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-2000:] or "Renderer did not create a safe image")
    except BaseException:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return output


def cleanup_image(image: Path) -> None:
    """Remove the temporary render directory once the image has been sent."""
    shutil.rmtree(Path(image).parent, ignore_errors=True)
