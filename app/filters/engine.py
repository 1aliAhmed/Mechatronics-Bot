from __future__ import annotations

import re
import threading

ARABIC_LETTERS = r"\u0621-\u063A\u0641-\u064A\u066E-\u06D3\u06FA-\u06FC\u0750-\u077F\u08A0-\u08C9"


class WordFilter:
    """In-memory wordlist matcher; persistence is the caller's job (the bot database)."""

    def __init__(self, words: dict[str, list[str]] | None = None):
        self._lock = threading.RLock()
        self.words: dict[str, list[str]] = {"en": [], "ar": []}
        self.load(words or {})

    def load(self, words: dict[str, list[str]]) -> None:
        with self._lock:
            self.words = {"en": [], "ar": []}
            for language, values in words.items():
                if language not in self.words:
                    continue
                seen = {word.casefold() for word in self.words[language]}
                for value in values:
                    word = value.strip()
                    if word and word.casefold() not in seen:
                        self.words[language].append(word)
                        seen.add(word.casefold())
            self._compile()

    def _compile(self) -> None:
        self.patterns: list[tuple[str, re.Pattern[str]]] = []
        for lang, words in self.words.items():
            for word in words:
                escaped = re.escape(word)
                if lang == "en":
                    expression = rf"(?<![A-Za-z]){escaped}(?![A-Za-z])"
                    flags = re.IGNORECASE
                else:
                    expression = rf"(?<![{ARABIC_LETTERS}]){escaped}(?![{ARABIC_LETTERS}])"
                    flags = 0
                self.patterns.append((word, re.compile(expression, flags)))

    def match(self, text: str) -> str | None:
        with self._lock:
            for word, pattern in self.patterns:
                if pattern.search(text):
                    return word
        return None

    def add(self, word: str, language: str | None = None) -> bool:
        word = word.strip()
        if not word:
            raise ValueError("word cannot be empty")
        language = language or ("ar" if any("\u0600" <= c <= "\u08ff" for c in word) else "en")
        if language not in self.words:
            raise ValueError("language must be en or ar")
        with self._lock:
            if word.casefold() in {w.casefold() for w in self.words[language]}:
                return False
            self.words[language].append(word)
            self._compile()
        return True

    def remove(self, word: str) -> bool:
        with self._lock:
            for lang, values in self.words.items():
                retained = [v for v in values if v.casefold() != word.casefold()]
                if len(retained) != len(values):
                    self.words[lang] = retained
                    self._compile()
                    return True
        return False
