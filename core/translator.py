from __future__ import annotations

import time
from typing import Callable, Iterable

PROVIDERS = ["google-free", "deepl"]


class Translator:
    def __init__(self, provider: str, source: str, target: str, deepl_key: str = ""):
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider {provider!r}; choose from {PROVIDERS}")
        self.provider = provider
        self.source = source
        self.target = target
        if provider == "deepl":
            if not deepl_key:
                raise ValueError("A DeepL API key is required for the 'deepl' provider.")
            from deep_translator import DeeplTranslator

            self._tr = DeeplTranslator(
                auth_key=deepl_key,
                source_lang=source.upper(),
                target_lang=target.upper(),
            )
        else:
            from deep_translator import GoogleTranslator

            self._tr = GoogleTranslator(source=source, target=target)

    def translate_one(self, word: str, retries: int = 3) -> str:
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                result = self._tr.translate(word)
                return (result or "").strip()
            except Exception as exc:  # rate limits, network hiccups
                last_exc = exc
                time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"Translation failed for {word!r}: {last_exc}")

    def translate_many(
        self,
        words: Iterable[str],
        progress: Callable[[int, int], None] | None = None,
        delay: float = 0.05,
    ) -> dict[str, str]:
        words = list(words)
        out: dict[str, str] = {}
        for i, word in enumerate(words):
            try:
                out[word] = self.translate_one(word)
            except RuntimeError:
                out[word] = ""
            if progress:
                progress(i + 1, len(words))
            if delay:
                time.sleep(delay)
        return out
