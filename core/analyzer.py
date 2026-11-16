from __future__ import annotations

from collections import Counter
from typing import Callable, Iterable

import spacy

_NLP = None

# Approximate character size of one processing chunk; split on whitespace so words are never cut.
CHUNK_SIZE = 100_000


def get_nlp():
    global _NLP
    if _NLP is None:
        _NLP = spacy.load("en_core_web_sm", disable=["ner", "parser", "senter"])
    return _NLP


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
    drop_propn: bool = True,
    drop_stopwords: bool = False,
    min_len: int = 2,
    progress: Callable[[float], None] | None = None,
) -> Counter:
    """Tokenize + lemmatize text and return a Counter of lemma frequencies.

    Only alphabetic tokens are kept (numbers/punctuation dropped), lemmas are
    lowercased, and 'running'/'ran'/'runs' all count as 'run'.
    """
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
