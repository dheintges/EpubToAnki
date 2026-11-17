from __future__ import annotations

import subprocess
import sys
from collections import Counter
from typing import Callable, Iterable

DEFAULT_MODEL = "en_core_web_sm"

# Approximate character size of one processing chunk; split on whitespace so words are never cut.
CHUNK_SIZE = 100_000

_NLP_CACHE: dict = {}


class ModelNotInstalledError(RuntimeError):
    pass


def installed_models() -> list[str]:
    import spacy.util

    return sorted(spacy.util.get_installed_models())


def download_model(name: str) -> str:
    """Download a spaCy model package via `python -m spacy download <name>`. Returns the output."""
    proc = subprocess.run(
        [sys.executable, "-m", "spacy", "download", name],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stdout + proc.stderr)[-2000:]
        raise RuntimeError(f"Download of spaCy model {name!r} failed:\n{tail}")
    return proc.stdout


def load_model(name: str = DEFAULT_MODEL):
    """Load (and cache) an installed spaCy model. Raises ModelNotInstalledError if missing."""
    if name in _NLP_CACHE:
        return _NLP_CACHE[name]
    import spacy

    if name not in spacy.util.get_installed_models():
        raise ModelNotInstalledError(
            f"spaCy model {name!r} is not installed. "
            f"Download it with: python -m spacy download {name}"
        )
    nlp = spacy.load(name, disable=["ner", "parser", "senter"])
    _NLP_CACHE[name] = nlp
    return nlp


def get_nlp(model: str = DEFAULT_MODEL):
    return load_model(model)


def chunk_text(text: str, size: int = CHUNK_SIZE) -> Iterable[str]:
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            cut = text.rfind(" ", start, end)
            if cut > start:
                end = cut
        yield text[start:end]
        start = end


def count_lemmas(
    text: str,
    *,
    nlp=None,
    drop_propn: bool = True,
    drop_stopwords: bool = False,
    min_len: int = 2,
    progress: Callable[[float], None] | None = None,
) -> Counter:
    """Tokenize + lemmatize text and return a Counter of lemma frequencies.

    Only alphabetic tokens are kept (numbers/punctuation dropped), lemmas are
    lowercased, and 'running'/'ran'/'runs' all count as 'run'. Pass an explicit
    `nlp` (from load_model) to use a non-default model; otherwise the default
    model is loaded lazily.
    """
    if nlp is None:
        nlp = get_nlp()
    counter: Counter = Counter()
    chunks = list(chunk_text(text))
    total = max(len(chunks), 1)
    for i, chunk in enumerate(chunks):
        for token in nlp(chunk):
            if not token.is_alpha:
                continue
            if drop_propn and token.pos_ == "PROPN":
                continue
            if drop_stopwords and token.is_stop:
                continue
            lemma = token.lemma_.lower().strip("-_'")
            if len(lemma) < min_len:
                continue
            counter[lemma] += 1
        if progress:
            progress((i + 1) / total)
    return counter


def top_words(counter: Counter, *, min_freq: int = 1, max_words: int | None = None) -> list[tuple[str, int]]:
    items = [(w, c) for w, c in counter.items() if c >= min_freq]
    items.sort(key=lambda kv: (-kv[1], kv[0]))
    if max_words is not None:
        items = items[:max_words]
    return items
