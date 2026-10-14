from __future__ import annotations

import re

# Emoji and pictograph ranges stripped from user-visible text.
_EMOJI_RANGES = (
    (0x1F000, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x2B00, 0x2BFF),
    (0x1F1E6, 0x1F1FF),
    (0xFE00, 0xFE0F),
    (0x200D, 0x200D),
    (0x2049, 0x2049),
    (0x203C, 0x203C),
)


def strip_emoji(text: str) -> str:
    kept = [ch for ch in text if not any(lo <= ord(ch) <= hi for lo, hi in _EMOJI_RANGES)]
    return "".join(kept)


def clean_markup(text: str) -> str:
    """Remove markdown artifacts that render as literal junk on Telegram plain text."""
    text = re.sub(r"```[^\n`]*\n(.*?)```", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"```([^`]*)```", r"\1", text)
    text = text.replace("`", "")
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\$\$([^$]+)\$\$", r"\1", text)
    text = re.sub(r"\$([^$\n]+)\$", r"\1", text)
    text = text.replace("\\(", "(").replace("\\)", ")").replace("\\[", "").replace("\\]", "")
    return text


def apply_style(text: str) -> str:
    """House style for model answers: no emoji, no markdown artifacts, clean spacing."""
    clean = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    clean = strip_emoji(clean)
    clean = clean_markup(clean)
    clean = re.sub(r"(?<=\S) {2,}(?=\S)", " ", clean)
    clean = re.sub(r"[ \t]+\n", "\n", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()
